import { describe, expect, it } from 'vitest';
import {
  classifySyncFailure, statusForFailure, computeBackoffMs, selectEligibleItems, resolveDependencyReferences,
} from '../../pwa/syncEngine';
import { SyncQueueItem } from '../../pwa/offlineTypes';

function makeItem(overrides: Partial<SyncQueueItem>): SyncQueueItem {
  return {
    queue_id: 'q1', tenant_id: 't1', user_id: 'u1', entity_type: 'SALES_INVOICE', operation_type: 'CREATE',
    client_transaction_id: 'ctx-1', local_reference: 'OFF-INV-1', payload: {}, depends_on: [], status: 'PENDING_SYNC',
    retry_count: 0, max_retries: 5, last_attempt_at: null, next_retry_at: null, last_error: null, server_id: null,
    final_reference: null, server_response: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('classifySyncFailure (PROMPT-028 §24/§54)', () => {
  it('classifies a network error (no HTTP status) as TRANSIENT', () => {
    const result = classifySyncFailure(null, undefined, 'Failed to fetch');
    expect(result.class).toBe('TRANSIENT');
  });

  it('classifies 5xx as TRANSIENT', () => {
    expect(classifySyncFailure(500, 'SERVER_ERROR', 'x').class).toBe('TRANSIENT');
    expect(classifySyncFailure(503, 'SERVICE_UNAVAILABLE', 'x').class).toBe('TRANSIENT');
  });

  it('classifies 401/403 as AUTHORIZATION', () => {
    expect(classifySyncFailure(401, 'AUTH_REQUIRED', 'x').class).toBe('AUTHORIZATION');
    expect(classifySyncFailure(403, 'FORBIDDEN', 'x').class).toBe('AUTHORIZATION');
  });

  it('classifies 409 as BUSINESS_CONFLICT', () => {
    expect(classifySyncFailure(409, 'STOCK_CONFLICT', 'x').class).toBe('BUSINESS_CONFLICT');
  });

  it('classifies 400/422 as VALIDATION', () => {
    expect(classifySyncFailure(400, 'BAD_REQUEST', 'x').class).toBe('VALIDATION');
    expect(classifySyncFailure(422, 'VALIDATION_ERROR', 'x').class).toBe('VALIDATION');
  });

  it('classifies 404 as DEPENDENCY_FAILURE', () => {
    expect(classifySyncFailure(404, 'NOT_FOUND', 'x').class).toBe('DEPENDENCY_FAILURE');
  });
});

describe('statusForFailure (PROMPT-028 §22/§23)', () => {
  it('keeps a transient failure eligible for retry until max_retries is reached', () => {
    const failure = classifySyncFailure(500, 'x', 'x');
    expect(statusForFailure(failure, 1, 5)).toBe('PENDING_SYNC');
    expect(statusForFailure(failure, 5, 5)).toBe('SYNC_FAILED');
  });

  it('never retries a validation failure — goes straight to REQUIRES_ACTION', () => {
    const failure = classifySyncFailure(422, 'x', 'x');
    expect(statusForFailure(failure, 1, 5)).toBe('REQUIRES_ACTION');
  });

  it('never retries an authorization failure', () => {
    const failure = classifySyncFailure(401, 'x', 'x');
    expect(statusForFailure(failure, 0, 5)).toBe('REQUIRES_ACTION');
  });

  it('routes a business conflict to CONFLICT, never auto-retried', () => {
    const failure = classifySyncFailure(409, 'STOCK_CONFLICT', 'x');
    expect(statusForFailure(failure, 0, 5)).toBe('CONFLICT');
  });
});

describe('computeBackoffMs (PROMPT-028 §22, exponential backoff)', () => {
  it('increases with each retry attempt', () => {
    const first = computeBackoffMs(0);
    const second = computeBackoffMs(1);
    const third = computeBackoffMs(2);
    // jitter is +/-15%, so compare against the un-jittered floor of each step
    expect(second).toBeGreaterThan(first * 0.8);
    expect(third).toBeGreaterThan(second * 0.8);
  });

  it('never exceeds the configured maximum delay', () => {
    const veryHighRetryCount = computeBackoffMs(20);
    expect(veryHighRetryCount).toBeLessThanOrEqual(5 * 60 * 1000 * 1.16); // cap + jitter margin
  });
});

describe('selectEligibleItems (PROMPT-028 §18/§44 dependency ordering)', () => {
  it('excludes an item whose dependency has not yet synced', () => {
    const customer = makeItem({ queue_id: 'c1', entity_type: 'CUSTOMER', status: 'PENDING_SYNC' });
    const invoice = makeItem({ queue_id: 'i1', entity_type: 'SALES_INVOICE', status: 'PENDING_SYNC', depends_on: ['c1'] });
    const eligible = selectEligibleItems([customer, invoice]);
    expect(eligible.map((i) => i.queue_id)).toEqual(['c1']);
  });

  it('includes a dependent item once its dependency has SYNCED', () => {
    const customer = makeItem({ queue_id: 'c1', entity_type: 'CUSTOMER', status: 'SYNCED', server_id: 'srv-1' });
    const invoice = makeItem({ queue_id: 'i1', entity_type: 'SALES_INVOICE', status: 'PENDING_SYNC', depends_on: ['c1'] });
    const eligible = selectEligibleItems([customer, invoice]);
    expect(eligible.map((i) => i.queue_id)).toEqual(['i1']);
  });

  it('excludes items that are not PENDING_SYNC (already synced/failed/conflict)', () => {
    const synced = makeItem({ queue_id: 's1', status: 'SYNCED' });
    const conflict = makeItem({ queue_id: 'x1', status: 'CONFLICT' });
    const pending = makeItem({ queue_id: 'p1', status: 'PENDING_SYNC' });
    const eligible = selectEligibleItems([synced, conflict, pending]);
    expect(eligible.map((i) => i.queue_id)).toEqual(['p1']);
  });
});

describe('resolveDependencyReferences (PROMPT-028 §18 — never submit a dangling local reference)', () => {
  it('replaces a __local_ref placeholder with the resolved server id', () => {
    const payload = { customer_id: { __local_ref: 'c1' }, notes: 'hello' };
    const resolved = resolveDependencyReferences(payload, new Map([['c1', 'server-customer-42']]));
    expect(resolved.customer_id).toBe('server-customer-42');
    expect(resolved.notes).toBe('hello');
  });

  it('leaves non-placeholder fields untouched', () => {
    const payload = { customer_id: 'already-a-server-id', lines: [{ product_id: 'p1' }] };
    const resolved = resolveDependencyReferences(payload, new Map());
    expect(resolved).toEqual(payload);
  });
});
