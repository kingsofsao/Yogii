import type { Band, PaymentState } from "../api/types";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });

export function formatINR(amount: string | number): string {
  const n = typeof amount === "string" ? Number(amount) : amount;
  return Number.isFinite(n) ? inr.format(n) : "₹—";
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export const BAND_LABEL: Record<Band, string> = {
  LOW: "Low risk",
  MEDIUM: "Medium risk",
  HIGH: "High risk",
  VERY_HIGH: "Very high risk",
};

export const STATE_LABEL: Record<PaymentState, string> = {
  DRAFT: "Draft",
  ASSESSING: "Ready to authorise",
  NEEDS_VERIFICATION: "Needs verification",
  BLOCKED: "Blocked",
  PENDING: "Pending",
  COMPLETED: "Completed",
  FAILED: "Failed",
  REVERSED: "Reversed",
};

export const BAND_GUIDANCE: Record<Band, { title: string; body: string }> = {
  LOW: {
    title: "No unusual signals",
    body: "This payment looks like your usual activity. You can authorise it.",
  },
  MEDIUM: {
    title: "Take a moment before you pay",
    body: "Some details are unusual for your account. Confirm the checks below to continue.",
  },
  HIGH: {
    title: "Strong warning: this payment looks risky",
    body: "Several signals are unusual. Only continue if you know this recipient and nobody is pressuring you to pay.",
  },
  VERY_HIGH: {
    title: "This payment was blocked",
    body: "The risk check stopped this simulated payment before authorisation. No money moved.",
  },
};
