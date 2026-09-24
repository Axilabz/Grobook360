import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { apiRequest, ConcurrencyConflictError } from '../../api/client';

describe('apiRequest (API client foundation)', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('parses the standard success envelope and returns only the data payload', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ data: { id: '1' }, meta: { correlation_id: 'abc' } }),
        { status: 200, headers: { 'X-Correlation-Id': 'abc' } }
      )
    );

    const result = await apiRequest<{ id: string }>('/health');
    expect(result).toEqual({ id: '1' });
  });

  it('sends a generated X-Correlation-Id header when making a request', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: {}, meta: { correlation_id: 'x' } }), { status: 200 })
    );

    await apiRequest('/health');

    const [, init] = (global.fetch as any).mock.calls[0];
    expect(init.headers['X-Correlation-Id']).toBeTruthy();
  });

  it('throws ApiError with the parsed error envelope on a non-2xx response', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: 'VALIDATION_ERROR', message: 'Invalid', details: [] },
          meta: { correlation_id: 'abc' },
        }),
        { status: 422 }
      )
    );

    await expect(apiRequest('/whatever')).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
      status: 422,
    });
  });

  it('throws ConcurrencyConflictError specifically on HTTP 412', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: 'CONCURRENCY_CONFLICT', message: 'Stale', details: [] },
          meta: { correlation_id: 'abc' },
        }),
        { status: 412 }
      )
    );

    await expect(apiRequest('/whatever')).rejects.toBeInstanceOf(ConcurrencyConflictError);
  });

  it('sends If-Match when expectedRowVersion is supplied', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: {}, meta: { correlation_id: 'x' } }), { status: 200 })
    );

    await apiRequest('/thing', { method: 'PATCH', expectedRowVersion: 4 });

    const [, init] = (global.fetch as any).mock.calls[0];
    expect(init.headers['If-Match']).toBe('4');
  });
});
