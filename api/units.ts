import { apiRequest } from './client';

export interface UnitOfMeasure {
  id: string;
  code: string;
  name: string;
  precision: number;
}

export async function listUnits(): Promise<UnitOfMeasure[]> {
  return apiRequest<UnitOfMeasure[]>('/units');
}

export interface CreateUnitPayload {
  code: string;
  name: string;
  precision?: number;
}

export async function createUnit(payload: CreateUnitPayload): Promise<UnitOfMeasure> {
  return apiRequest<UnitOfMeasure>('/units', { method: 'POST', body: payload });
}
