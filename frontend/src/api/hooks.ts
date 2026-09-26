import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Dashboard, Me, ModelInfo, Payment, PaymentList, Preferences, Recipient, SecurityEvent, SessionResponse, Settings,
  SimulatedOutcome,
} from "./types";

export const keys = {
  me: ["me"] as const,
  dashboard: ["dashboard"] as const,
  payments: (filters: object) => ["payments", filters] as const,
  payment: (id: number) => ["payment", id] as const,
  recipients: ["recipients"] as const,
  settings: ["settings"] as const,
  securityEvents: ["security-events"] as const,
  model: ["model-info"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api<Me>("/me"), retry: false });
export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: () => api<Dashboard>("/dashboard") });
export const useRecipients = () => useQuery({ queryKey: keys.recipients, queryFn: () => api<Recipient[]>("/recipients") });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api<Settings>("/settings") });
export const useModelInfo = () => useQuery({ queryKey: keys.model, queryFn: () => api<ModelInfo>("/model/info") });
export const useSecurityEvents = () =>
  useQuery({ queryKey: keys.securityEvents, queryFn: () => api<SecurityEvent[]>("/me/security-events") });

export function usePayments(filters: { state?: string; band?: string; limit: number }) {
  const params = new URLSearchParams({ limit: String(filters.limit) });
  if (filters.state) params.set("state", filters.state);
  if (filters.band) params.set("band", filters.band);
  return useQuery({ queryKey: keys.payments(filters), queryFn: () => api<PaymentList>(`/payments?${params}`) });
}

export const usePayment = (id: number) =>
  useQuery({ queryKey: keys.payment(id), queryFn: () => api<Payment>(`/payments/${id}`), enabled: Number.isFinite(id) });

function useInvalidatePayments() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: keys.dashboard });
    qc.invalidateQueries({ queryKey: ["payments"] });
    qc.invalidateQueries({ queryKey: ["payment"] });
    qc.invalidateQueries({ queryKey: keys.me });
  };
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { identifier: string; password: string }) =>
      api<SessionResponse>("/auth/login", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { full_name: string; email: string; phone: string; upi_id: string; password: string }) =>
      api<SessionResponse>("/auth/register", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useLogout(everywhere = false) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api(everywhere ? "/auth/logout-all" : "/auth/logout", { method: "POST" }),
    onSettled: () => qc.clear(),
  });
}

export function useAssess() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: (v: {
      recipient_upi: string; amount: number; note: string; device: string; location: string; key: string;
    }) =>
      api<Payment>("/payments/assess", {
        method: "POST",
        idempotencyKey: v.key,
        body: {
          recipient_upi: v.recipient_upi, amount: v.amount, note: v.note,
          simulated_context: { device: v.device, location: v.location },
        },
      }),
    onSuccess: invalidate,
  });
}

export function useAuthorize() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: (v: { payment_id: number; demo_verification_confirmed: boolean; simulated_outcome: SimulatedOutcome; key: string }) =>
      api<Payment>("/payments", {
        method: "POST",
        idempotencyKey: v.key,
        body: {
          payment_id: v.payment_id,
          demo_verification_confirmed: v.demo_verification_confirmed,
          simulated_outcome: v.simulated_outcome,
        },
      }),
    onSuccess: invalidate,
  });
}

export function useCancelPayment() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: (id: number) => api<Payment>(`/payments/${id}/cancel`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useRefreshStatus() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: (id: number) => api<{ state: string }>(`/payments/${id}/status`),
    onSuccess: invalidate,
  });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Preferences>) => api<Settings>("/settings", { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(keys.settings, data);
      qc.invalidateQueries({ queryKey: keys.dashboard });
    },
  });
}
