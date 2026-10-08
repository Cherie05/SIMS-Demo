import axios from 'axios';
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form';
import type { FieldError } from '../api/client';
import type { ApiErrorBody } from '../types';

/**
 * Map API errors onto form fields: 422 field-level validation details, and 409 conflicts
 * listed in `conflicts` (e.g. DUPLICATE_SKU -> 'sku'). Returns true when something was mapped.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  conflicts: Record<string, Path<T>> = {},
): boolean {
  if (!axios.isAxiosError<ApiErrorBody>(error)) return false;
  const body = error.response?.data?.error;
  if (!body) return false;

  if (conflicts[body.code]) {
    setError(conflicts[body.code], { type: 'server', message: body.message });
    return true;
  }
  if (body.code === 'VALIDATION_ERROR' && Array.isArray(body.details)) {
    let mapped = false;
    for (const detail of body.details as FieldError[]) {
      if (detail.field) {
        setError(detail.field as Path<T>, { type: 'server', message: detail.message });
        mapped = true;
      }
    }
    return mapped;
  }
  return false;
}
