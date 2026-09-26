// Mirrors backend/schemas.py. Every amount is a decimal string in rupees.

export type Band = "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
export type PaymentState =
  | "DRAFT" | "ASSESSING" | "NEEDS_VERIFICATION" | "BLOCKED" | "PENDING" | "COMPLETED" | "FAILED" | "REVERSED";
export type SimulatedOutcome = "SUCCESS" | "FAILURE" | "PENDING";

export interface UserProfile {
  id: number;
  full_name: string;
  email: string;
  phone: string;
  upi_id: string;
  status: string;
  created_at: string | null;
  last_login_at: string | null;
}

export interface Me extends UserProfile {
  simulated_balance: string;
  currency: string;
  is_simulated: boolean;
  mode: string;
}

export interface SessionResponse {
  user: UserProfile;
  csrf_token: string;
  expires_at: string;
  mode: string;
}

export interface Recipient {
  name: string;
  upi_id: string;
  payment_type: "P2P" | "P2M";
  kind: "yogii_user" | "merchant" | "contact" | "unverified";
  merchant_category: string | null;
  is_fictional_demo: boolean;
  notice: string | null;
}

export interface ReasonCode {
  code: string;
  description: string;
}

export interface Risk {
  score: number;
  band: Band;
  decision: "ALLOW" | "VERIFY" | "BLOCK";
  requires_verification: boolean;
  blocked: boolean;
  reason_codes: ReasonCode[];
  score_kind: string;
  model_version: string;
  policy_version: string;
  assessed_at: string;
}

export interface Payment {
  id: number;
  reference: string;
  mode: string;
  is_simulated: boolean;
  direction: "outgoing";
  state: PaymentState;
  amount: string;
  currency: string;
  recipient: { name: string; upi_id: string; payment_type: string };
  note: string | null;
  failure_reason: string | null;
  simulated_outcome: string | null;
  provider: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  risk: Risk | null;
  actions: { can_authorize: boolean; needs_verification: boolean; can_cancel: boolean; can_refresh_status: boolean };
  timeline: { state: string; reason: string | null; at: string }[] | null;
}

export interface Incoming {
  id: number;
  direction: "incoming";
  reference: string;
  amount: string;
  currency: string;
  from_name: string;
  state: string;
  is_simulated: boolean;
  created_at: string;
}

export interface PaymentList {
  items: Payment[];
  total: number;
  limit: number;
  offset: number;
}

export interface Dashboard {
  user: UserProfile;
  simulated_balance: string;
  currency: string;
  mode: string;
  is_simulated: boolean;
  notice: string;
  stats: Record<"completed" | "blocked" | "failed" | "pending" | "awaiting_action", number>;
  recent_payments: Payment[];
  recent_incoming: Incoming[];
  hide_balance: boolean;
}

export interface Preferences {
  hide_balance: boolean;
  notify_on_high_risk: boolean;
  theme: "system" | "light" | "dark";
}

export interface Settings {
  mode: string;
  live_payments_enabled: boolean;
  live_payments_note: string;
  provider: string;
  risk_policy_version: string;
  risk_bands: Record<Band, string>;
  thresholds_note: string;
  max_payment_amount: number;
  history_window_days: number;
  graph_depth: number;
  data_retention_days: Record<string, number>;
  preferences: Preferences;
}

export interface SecurityEvent {
  event_type: string;
  severity: string;
  created_at: string;
}

export interface ModelInfo {
  model_version: string;
  loaded: boolean;
  algorithm: string | null;
  training_date: string | null;
  score_kind: string | null;
  metrics: Record<string, unknown>;
  is_synthetic: boolean;
  risk_bands: Record<Band, string>;
  disclaimer: string;
}
