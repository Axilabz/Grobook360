// Reusable frontend API client foundation (PROMPT-001 S16).
//
// No business calls exist yet. This establishes: base URL, auth-token header,
// JSON requests, standard success/error envelope parsing, correlation-id
// propagation, HTTP status handling and row_version (If-Match) support.
// Financial mutations are never auto-retried here — only the caller decides
// that, and only when the operation is idempotent (Idempotency-Key supplied).

import type { ApiErrorBody, ApiErrorEnvelope, ApiList, ApiSuccess } from './envelopes';

const API_BASE_URL: string =
  (import.meta as any).env?.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: ApiErrorBody['details'];
  readonly correlationId?: string;

  constructor(status: number, body: ApiErrorBody, correlationId?: string) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.correlationId = correlationId;
  }
}

/** Row-version conflict (HTTP 412) — the caller must refresh and re-apply, never silently overwrite. */
export class ConcurrencyConflictError extends ApiError {}

function generateCorrelationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

// PROMPT-003 S22: lets AuthContext learn about a 401 from ANY protected call
// (not just the initial session-restoration probe) so it can distinguish
// "never logged in" from "session expired mid-use" and react accordingly.
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Expected row_version for optimistic-concurrency updates (sent as If-Match). */
  expectedRowVersion?: number;
  /** Required for offline/financial create operations the server treats as idempotent. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function rawRequest(path: string, options: RequestOptions): Promise<{ payload: any; correlationId: string; status: number }> {
  const correlationId = generateCorrelationId();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    'X-Correlation-Id': correlationId,
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  if (options.expectedRowVersion !== undefined) {
    headers['If-Match'] = String(options.expectedRowVersion);
  }
  if (options.idempotencyKey) {
    headers['Idempotency-Key'] = options.idempotencyKey;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    // PROMPT-003: the session token travels as an httpOnly cookie, not a
    // JS-readable store — this is what actually attaches it to the request.
    credentials: 'include',
  });

  const responseCorrelationId = response.headers.get('X-Correlation-Id') ?? correlationId;

  if (response.status === 204) {
    return { payload: undefined, correlationId: responseCorrelationId, status: response.status };
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const errorEnvelope = payload as ApiErrorEnvelope | null;
    const errorBody: ApiErrorBody = errorEnvelope?.error ?? {
      code: 'UNKNOWN_ERROR',
      message: `Request failed with status ${response.status}`,
      details: [],
    };
    if (response.status === 412) {
      throw new ConcurrencyConflictError(response.status, errorBody, responseCorrelationId);
    }
    if (response.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    throw new ApiError(response.status, errorBody, responseCorrelationId);
  }

  return { payload, correlationId: responseCorrelationId, status: response.status };
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { payload } = await rawRequest(path, options);
  return (payload as ApiSuccess<T>)?.data as T;
}

/** For list endpoints: returns data + pagination rather than discarding pagination. */
export async function apiRequestList<T>(path: string, options: RequestOptions = {}): Promise<ApiList<T>> {
  const { payload } = await rawRequest(path, options);
  return payload as ApiList<T>;
}

/** For endpoints whose `meta` carries caller-relevant info beyond correlation_id/timestamp (e.g. the Analysis API's server-resolved date range) — returns both `data` and `meta` instead of discarding `meta`. */
export async function apiRequestWithMeta<T, M = Record<string, unknown>>(path: string, options: RequestOptions = {}): Promise<{ data: T; meta: M }> {
  const { payload } = await rawRequest(path, options);
  return payload as { data: T; meta: M };
}
