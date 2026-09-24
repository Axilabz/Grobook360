// Global Table/Grid Export Framework — frontend API client.
//
// A binary (xlsx/pdf) response doesn't fit apiRequest's JSON-envelope
// assumption, so this makes its own fetch call reusing the same base
// URL/credentials/correlation-id conventions as api/client.ts, then
// triggers a browser download from the returned blob.

const API_BASE_URL: string =
  (import.meta as any).env?.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export type ExportFormat = 'xlsx' | 'pdf';
export type ExportScope = 'CURRENT_PAGE' | 'ALL_FILTERED';

export interface ExportRequestParams {
  resource: string;
  format: ExportFormat;
  scope: ExportScope;
  search?: string;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
  partyId?: string;
  page?: number;
  pageSize?: number;
}

export class ExportError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ExportError';
    this.status = status;
    this.code = code;
  }
}

function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match ? match[1] : fallback;
}

/** Requests an export and triggers the browser's own file-save flow. Throws ExportError on failure (including 403 EXPORT-UNAUTHORIZED — the caller should have already hidden the button via hasPermission, this is the defense-in-depth backend check). */
export async function requestExport(params: ExportRequestParams): Promise<void> {
  const correlationId =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const response = await fetch(`${API_BASE_URL}/exports`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/octet-stream, application/json',
      'X-Correlation-Id': correlationId,
    },
    credentials: 'include',
    body: JSON.stringify({
      resource: params.resource,
      format: params.format,
      scope: params.scope,
      search: params.search || undefined,
      status: params.status || undefined,
      date_from: params.dateFrom || undefined,
      date_to: params.dateTo || undefined,
      party_id: params.partyId || undefined,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 25,
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const errorBody = payload?.error ?? { code: 'UNKNOWN_ERROR', message: `Export failed with status ${response.status}` };
    throw new ExportError(response.status, errorBody.code, errorBody.message);
  }

  const blob = await response.blob();
  const filename = filenameFromContentDisposition(
    response.headers.get('Content-Disposition'),
    `${params.resource}-export.${params.format}`
  );

  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
