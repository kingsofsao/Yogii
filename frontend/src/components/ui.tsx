import { AlertTriangle, CheckCircle2, Clock, Loader2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { Band, PaymentState } from "../api/types";
import { BAND_LABEL, STATE_LABEL } from "../lib/format";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function Card({ children, className, as: As = "section", ...rest }: {
  children: ReactNode; className?: string; as?: "section" | "div" | "article"; "aria-labelledby"?: string;
}) {
  return (
    <As className={cx("min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900", className)} {...rest}>
      {children}
    </As>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
};

export function Button({ variant = "primary", loading, className, children, disabled, ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-teal-700 text-white hover:bg-teal-800 dark:bg-teal-500 dark:text-slate-950 dark:hover:bg-teal-400",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800",
    danger: "bg-red-700 text-white hover:bg-red-800",
    ghost: "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition",
        "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-not-allowed disabled:opacity-50",
        styles, className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Field({ id, label, hint, error, children }: {
  id: string; label: string; hint?: string; error?: string; children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-slate-800 dark:text-slate-200">{label}</label>
      {children}
      {hint && !error && <p id={`${id}-hint`} className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
      {error && <p id={`${id}-error`} className="text-sm font-medium text-red-700 dark:text-red-400">{error}</p>}
    </div>
  );
}

export const inputClass =
  "min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900 placeholder:text-slate-400 " +
  "focus:border-teal-600 focus:outline-3 focus:outline-teal-600/30 aria-[invalid=true]:border-red-600 " +
  "dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100";

export function SimTag({ className }: { className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-300", className)}>
      Simulated
    </span>
  );
}

const bandStyle: Record<Band, string> = {
  LOW: "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-800",
  MEDIUM: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-800",
  HIGH: "bg-orange-50 text-orange-800 ring-orange-200 dark:bg-orange-950 dark:text-orange-300 dark:ring-orange-800",
  VERY_HIGH: "bg-red-50 text-red-800 ring-red-200 dark:bg-red-950 dark:text-red-300 dark:ring-red-800",
};

export function RiskBadge({ band }: { band: Band }) {
  const Icon = band === "LOW" ? ShieldCheck : band === "VERY_HIGH" ? ShieldAlert : AlertTriangle;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", bandStyle[band])}>
      <Icon className="size-3.5" aria-hidden />
      {BAND_LABEL[band]}
    </span>
  );
}

const stateStyle: Partial<Record<PaymentState, string>> = {
  COMPLETED: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  PENDING: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  NEEDS_VERIFICATION: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  ASSESSING: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  BLOCKED: "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300",
  FAILED: "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function StateBadge({ state }: { state: PaymentState }) {
  const Icon = state === "COMPLETED" ? CheckCircle2 : state === "PENDING" ? Clock : ["BLOCKED", "FAILED"].includes(state) ? XCircle : null;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", stateStyle[state] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200")}>
      {Icon && <Icon className="size-3.5" aria-hidden />}
      {STATE_LABEL[state]}
    </span>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-12 text-slate-600 dark:text-slate-300">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      <p className="flex items-center gap-2 font-medium"><XCircle className="size-5" aria-hidden />{message}</p>
      {onRetry && <Button variant="secondary" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <p className="font-semibold text-slate-800 dark:text-slate-100">{title}</p>
      {body && <p className="max-w-sm text-sm text-slate-600 dark:text-slate-400">{body}</p>}
      {action}
    </div>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight text-slate-900 outline-none dark:text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-slate-600 dark:text-slate-400">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}
