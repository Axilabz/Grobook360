// Mirrors the backend's standard API envelopes (API Contract Specification v1.0 S6).

export interface ApiMeta {
  correlation_id: string;
  timestamp?: string;
}

export interface ApiSuccess<T> {
  data: T;
  meta: ApiMeta;
}

export interface ApiPagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

export interface ApiList<T> {
  data: T[];
  pagination: ApiPagination;
  meta: ApiMeta;
}

export interface ApiErrorDetail {
  field?: string;
  code: string;
  message: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: ApiErrorDetail[];
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
  meta: ApiMeta;
}
