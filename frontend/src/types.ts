export type Role = 'ADMIN' | 'MANAGER' | 'SALES';
export type OrderStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'COMPLETED' | 'REJECTED' | 'CANCELLED';
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED';
export type InventoryTxnType = 'OPENING' | 'SALE' | 'RESTOCK' | 'ADJUSTMENT';
/** QUEUED: waiting in the outbox for the background worker (retried with backoff if delivery fails). */
export type EmailStatus = 'SENT' | 'FAILED' | 'SKIPPED' | 'QUEUED';

/** Fine-grained permissions; the API enforces them, the UI only uses them to hide what can't be used. */
export type Permission =
  | 'dashboard:read'
  | 'product:read'
  | 'product:write'
  | 'stock:adjust'
  | 'inventory:read'
  | 'customer:read'
  | 'customer:write'
  | 'customer:deactivate'
  | 'order:create'
  | 'order:read:own'
  | 'order:read:all'
  | 'order:cancel:any'
  | 'order:approve'
  | 'settings:read'
  | 'settings:write'
  | 'user:manage'
  | 'audit:read'
  | 'system:read'
  | 'system:operate';

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserSummary {
  id: number;
  name: string;
  email: string;
  role: Role;
}

export interface User extends UserSummary {
  is_active: boolean;
  is_verified: boolean;
  totp_enabled: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** The signed-in user, with what they may do. */
export interface CurrentUser extends User {
  permissions: Permission[];
  password_changed_at: string | null;
}

export type OtpPurpose = 'SIGNUP' | 'LOGIN' | 'PASSWORD_RESET';

/** Returned by sign-in and sign-up when a one-time code is needed to continue. */
export interface OtpChallenge {
  otp_required: true;
  challenge_id: string;
  purpose: OtpPurpose;
  /** code: 6 digits delivered by log/email; totp: from the user's authenticator app (or a recovery code) */
  method: 'code' | 'totp';
  delivery: 'log' | 'email' | 'authenticator';
  destination: string | null;
  expires_in: number;
  resend_available_in: number;
  code_length: number;
}

/** A signed-in session. The refresh token is in an httpOnly cookie, never visible to scripts. */
export interface Session {
  otp_required: false;
  access_token: string;
  token_type: string;
  expires_in: number;
  session_id: string;
  /** Seconds until the session ends regardless of activity. */
  session_expires_in: number;
  user: CurrentUser;
}

export interface AuthConfig {
  signup_enabled: boolean;
  signup_allowed_domains: string[];
  login_otp_required: boolean;
  otp_delivery: 'log' | 'email';
  demo_accounts: boolean;
  session_idle_timeout_seconds: number;
  password_min_length: number;
  password_max_length: number;
}

export interface CustomerSummary {
  id: number;
  name: string;
  email: string;
}

export interface Customer extends CustomerSummary {
  phone: string | null;
  address: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductSummary {
  id: number;
  sku: string;
  name: string;
}

export interface Product extends ProductSummary {
  description: string | null;
  unit_price: number;
  stock_qty: number;
  reorder_level: number;
  is_active: boolean;
  is_low_stock: boolean;
  created_at: string;
  updated_at: string;
}

export interface InventoryTransaction {
  id: number;
  product: ProductSummary;
  order_id: number | null;
  txn_type: InventoryTxnType;
  qty_change: number;
  balance_after: number;
  note: string | null;
  created_by: UserSummary | null;
  created_at: string;
}

export interface OrderItem {
  id: number;
  product: ProductSummary;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface Approval {
  id: number;
  status: ApprovalStatus;
  threshold_amount: number;
  requested_at: string;
  decided_by: UserSummary | null;
  decided_at: string | null;
  comment: string | null;
}

export interface StatusHistory {
  id: number;
  from_status: OrderStatus | null;
  to_status: OrderStatus;
  changed_by: UserSummary | null;
  comment: string | null;
  created_at: string;
}

export interface EmailLog {
  id: number;
  to_email: string;
  subject: string;
  template: string;
  status: EmailStatus;
  error: string | null;
  created_at: string;
}

export interface OrderListItem {
  id: number;
  order_number: string;
  status: OrderStatus;
  customer: CustomerSummary;
  created_by: UserSummary;
  total_amount: number;
  requires_approval: boolean;
  created_at: string;
  completed_at: string | null;
}

export interface Order extends OrderListItem {
  subtotal: number;
  tax_rate: number;
  tax_amount: number;
  notes: string | null;
  items: OrderItem[];
  approval: Approval | null;
  history: StatusHistory[];
  emails: EmailLog[];
}

export interface ApprovalListItem extends Approval {
  order: OrderListItem;
}

export interface DashboardSummary {
  sales: {
    total_revenue: number;
    revenue_this_month: number;
    revenue_today: number;
    completed_orders: number;
    average_order_value: number;
  };
  orders: { total: number; pending_approval: number; completed: number; rejected: number; cancelled: number };
  approvals: {
    pending: number;
    approved: number;
    rejected: number;
    cancelled: number;
    pending_value: number;
    average_decision_hours: number | null;
  };
  inventory: {
    active_products: number;
    total_units: number;
    inventory_value: number;
    low_stock: number;
    out_of_stock: number;
  };
  customers: number;
}

export interface SalesTrendPoint {
  date: string;
  revenue: number;
  orders: number;
}

export interface TopProduct {
  product_id: number;
  sku: string;
  name: string;
  quantity_sold: number;
  revenue: number;
}

export interface AppSettings {
  approval_threshold: number;
  tax_rate: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown; request_id?: string | null };
}

// ---------------------------------------------------------------- account security

export interface PasswordForgotResult {
  message: string;
  delivery: 'log' | 'email';
  expires_in: number;
  resend_available_in: number;
  code_length: number;
}

export interface SessionInfo {
  id: string;
  current: boolean;
  authenticated_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
  mfa_method: string | null;
}

export interface MfaStatus {
  totp_enabled: boolean;
  totp_enabled_at: string | null;
  recovery_codes_remaining: number;
  method: 'totp' | 'code' | 'none';
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg_data_uri: string;
}

// ---------------------------------------------------------------- operations

export interface AuditLogEntry {
  id: number;
  occurred_at: string;
  actor_id: number | null;
  actor_email: string | null;
  actor_role: string | null;
  action: string;
  outcome: 'success' | 'failure' | 'denied';
  entity_type: string | null;
  entity_id: string | null;
  changes: Record<string, { old: unknown; new: unknown }> | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  request_id: string | null;
}

export type JobStatus = 'PENDING' | 'RUNNING' | 'RETRY' | 'DONE' | 'DEAD' | 'EXPIRED';

export interface Job {
  id: number;
  job_type: string;
  status: JobStatus;
  priority: number;
  attempts: number;
  max_attempts: number;
  available_at: string;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  last_error: string | null;
  request_id: string | null;
  reference: Record<string, string | number>;
}

export interface DependencyStatus {
  status: 'ok' | 'degraded' | 'down' | 'not_configured' | 'unknown';
  detail?: string | null;
}

export interface WorkerInfo {
  worker_id: string;
  hostname: string;
  version: string;
  started_at: string;
  last_seen_at: string;
  jobs_processed: number;
  alive: boolean;
}

export interface ScheduledTask {
  name: string;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_result: Record<string, number> | null;
  run_count: number;
}

export interface SystemStatus {
  version: string;
  environment: string;
  uptime_seconds: number;
  database: DependencyStatus;
  redis: DependencyStatus;
  migrations: DependencyStatus;
  workers: WorkerInfo[];
  jobs: Record<JobStatus, number>;
  oldest_due_job_age_seconds: number;
  scheduled_tasks: ScheduledTask[];
}

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  default: boolean;
  description: string;
}
