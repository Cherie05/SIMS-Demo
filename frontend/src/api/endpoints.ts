import { api } from './client';
import type {
  AppSettings,
  ApprovalListItem,
  ApprovalStatus,
  AuditLogEntry,
  AuthConfig,
  CurrentUser,
  Customer,
  DashboardSummary,
  FeatureFlag,
  InventoryTransaction,
  InventoryTxnType,
  Job,
  JobStatus,
  MfaStatus,
  Order,
  OrderListItem,
  OrderStatus,
  OtpChallenge,
  Page,
  PasswordForgotResult,
  Product,
  Role,
  SalesTrendPoint,
  Session,
  SessionInfo,
  SystemStatus,
  TopProduct,
  TotpSetup,
  User,
} from '../types';

export interface PageQuery {
  page?: number;
  page_size?: number;
}

/** Drop empty filters so they don't end up in the query string. */
const clean = <T extends object>(params: T) =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));

// `signal` lets TanStack Query cancel a request whose result is no longer wanted (e.g. typing in a search box).
const get = async <T>(url: string, params?: object, signal?: AbortSignal) =>
  (await api.get<T>(url, { params: params && clean(params), signal })).data;
const post = async <T>(url: string, body?: unknown, headers?: Record<string, string>) =>
  (await api.post<T>(url, body, { headers })).data;
const patch = async <T>(url: string, body: unknown) => (await api.patch<T>(url, body)).data;
const put = async <T>(url: string, body: unknown) => (await api.put<T>(url, body)).data;
const del = async <T>(url: string) => (await api.delete<T>(url)).data;

/** Retries of the same submission reuse its key, so the server applies it once (no duplicate orders). */
const idempotent = (key?: string) => (key ? { 'Idempotency-Key': key } : undefined);

// ---------------------------------------------------------------- auth & account
export interface SignupInput {
  name: string;
  email: string;
  password: string;
}
export const authApi = {
  config: () => get<AuthConfig>('/auth/config'),
  /** Password step: returns a second-factor challenge, or a session when the second step is off. */
  login: (email: string, password: string) => post<OtpChallenge | Session>('/auth/login', { email, password }),
  signup: (data: SignupInput) => post<OtpChallenge>('/auth/signup', data),
  verifyOtp: (challengeId: string, code: string) =>
    post<Session>('/auth/otp/verify', { challenge_id: challengeId, code }),
  verifyRecoveryCode: (challengeId: string, recoveryCode: string) =>
    post<Session>('/auth/otp/verify', { challenge_id: challengeId, recovery_code: recoveryCode }),
  resendOtp: (challengeId: string) => post<OtpChallenge>('/auth/otp/resend', { challenge_id: challengeId }),
  logout: () => post<void>('/auth/logout'),
  me: () => get<CurrentUser>('/auth/me'),

  forgotPassword: (email: string) => post<PasswordForgotResult>('/auth/password/forgot', { email }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    post<void>('/auth/password/reset', { email, code, new_password: newPassword }),
  changePassword: (currentPassword: string, newPassword: string) =>
    post<void>('/auth/password/change', { current_password: currentPassword, new_password: newPassword }),

  sessions: () => get<SessionInfo[]>('/auth/sessions'),
  revokeSession: (id: string) => del<void>(`/auth/sessions/${encodeURIComponent(id)}`),
  revokeAllSessions: async (keepCurrent: boolean) =>
    (await api.post<{ revoked: number }>('/auth/sessions/revoke-all', null, { params: { keep_current: keepCurrent } }))
      .data,

  mfa: () => get<MfaStatus>('/auth/mfa'),
  totpSetup: (password: string) => post<TotpSetup>('/auth/mfa/totp/setup', { password }),
  totpEnable: (code: string) => post<{ recovery_codes: string[] }>('/auth/mfa/totp/enable', { code }),
  totpDisable: (password: string) => post<void>('/auth/mfa/totp/disable', { password }),
  regenerateRecoveryCodes: (password: string) =>
    post<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes', { password }),
};

export interface UserInput {
  name: string;
  email: string;
  password: string;
  role: Role;
}
export const usersApi = {
  list: (q: PageQuery & { role?: Role }, signal?: AbortSignal) => get<Page<User>>('/users', q, signal),
  create: (data: UserInput) => post<User>('/users', data),
  update: (id: number, data: Partial<Omit<UserInput, 'email'>> & { is_active?: boolean }) =>
    patch<User>(`/users/${id}`, data),
  revokeSessions: (id: number) => post<{ revoked: number }>(`/users/${id}/sessions/revoke`),
  resetMfa: (id: number) => post<User>(`/users/${id}/mfa/reset`),
};

// ---------------------------------------------------------------- customers
export interface CustomerInput {
  name: string;
  email: string;
  phone?: string | null;
  address?: string | null;
}
export const customersApi = {
  list: (q: PageQuery & { search?: string; is_active?: boolean }, signal?: AbortSignal) =>
    get<Page<Customer>>('/customers', q, signal),
  create: (data: CustomerInput) => post<Customer>('/customers', data),
  update: (id: number, data: Partial<CustomerInput> & { is_active?: boolean }) =>
    patch<Customer>(`/customers/${id}`, data),
  deactivate: (id: number) => del<Customer>(`/customers/${id}`),
};

// ---------------------------------------------------------------- products & inventory
export interface ProductInput {
  sku: string;
  name: string;
  description?: string | null;
  unit_price: number;
  reorder_level: number;
  opening_stock?: number;
}
export interface StockAdjustmentInput {
  txn_type: 'RESTOCK' | 'ADJUSTMENT';
  quantity: number;
  note?: string;
}
export const productsApi = {
  list: (q: PageQuery & { search?: string; is_active?: boolean; low_stock?: boolean }, signal?: AbortSignal) =>
    get<Page<Product>>('/products', q, signal),
  get: (id: number) => get<Product>(`/products/${id}`),
  create: (data: ProductInput) => post<Product>('/products', data),
  update: (id: number, data: Partial<Omit<ProductInput, 'opening_stock'>> & { is_active?: boolean }) =>
    patch<Product>(`/products/${id}`, data),
  deactivate: (id: number) => del<Product>(`/products/${id}`),
  adjustStock: (id: number, data: StockAdjustmentInput, idempotencyKey?: string) =>
    post<InventoryTransaction>(`/products/${id}/stock-adjustments`, data, idempotent(idempotencyKey)),
};

export const inventoryApi = {
  transactions: (q: PageQuery & { product_id?: number; txn_type?: InventoryTxnType }, signal?: AbortSignal) =>
    get<Page<InventoryTransaction>>('/inventory/transactions', q, signal),
};

// ---------------------------------------------------------------- orders & approvals
export interface OrderInput {
  customer_id: number;
  items: { product_id: number; quantity: number }[];
  notes?: string;
}
export interface OrderQuery extends PageQuery {
  status?: OrderStatus;
  search?: string;
  date_from?: string;
  date_to?: string;
  mine?: boolean;
}
export const ordersApi = {
  list: (q: OrderQuery, signal?: AbortSignal) => get<Page<OrderListItem>>('/orders', q, signal),
  get: (id: number, signal?: AbortSignal) => get<Order>(`/orders/${id}`, undefined, signal),
  create: (data: OrderInput, idempotencyKey?: string) => post<Order>('/orders', data, idempotent(idempotencyKey)),
  cancel: (id: number, reason?: string) => post<Order>(`/orders/${id}/cancel`, { reason: reason || null }),
  approve: (id: number, comment?: string) => post<Order>(`/orders/${id}/approve`, { comment: comment || null }),
  reject: (id: number, comment: string) => post<Order>(`/orders/${id}/reject`, { comment }),
};

export const approvalsApi = {
  list: (q: PageQuery & { status?: ApprovalStatus | '' }, signal?: AbortSignal) =>
    get<Page<ApprovalListItem>>('/approvals', q, signal),
};

// ---------------------------------------------------------------- dashboard & settings
export const dashboardApi = {
  summary: () => get<DashboardSummary>('/dashboard/summary'),
  salesTrend: (days = 30) => get<SalesTrendPoint[]>('/dashboard/sales-trend', { days }),
  topProducts: (limit = 5, days?: number) => get<TopProduct[]>('/dashboard/top-products', { limit, days }),
};

export const settingsApi = {
  get: () => get<AppSettings>('/settings'),
  update: (data: Partial<AppSettings>) => put<AppSettings>('/settings', data),
};

// ---------------------------------------------------------------- operations (admin)
export interface AuditQuery extends PageQuery {
  action?: string;
  actor_id?: number;
  entity_type?: string;
  entity_id?: string;
  outcome?: 'success' | 'failure' | 'denied' | '';
  date_from?: string;
  date_to?: string;
}
export const auditApi = {
  list: (q: AuditQuery, signal?: AbortSignal) => get<Page<AuditLogEntry>>('/audit-logs', q, signal),
  /** CSV download (the request carries the bearer token, so it can't be a plain link). */
  exportCsv: async (q: Omit<AuditQuery, 'page' | 'page_size'>) => {
    const response = await api.get<Blob>('/audit-logs/export', { params: clean(q), responseType: 'blob' });
    const disposition = String(response.headers['content-disposition'] ?? '');
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'sims-audit.csv';
    return { blob: response.data, filename };
  },
};

export const systemApi = {
  status: () => get<SystemStatus>('/system/status'),
  jobs: (q: PageQuery & { status?: JobStatus | ''; job_type?: string }, signal?: AbortSignal) =>
    get<Page<Job>>('/system/jobs', q, signal),
  retryJob: (id: number) => post<Job>(`/system/jobs/${id}/retry`),
  flags: () => get<FeatureFlag[]>('/feature-flags'),
  setFlag: (name: string, enabled: boolean) =>
    put<FeatureFlag>(`/feature-flags/${encodeURIComponent(name)}`, { enabled }),
};
