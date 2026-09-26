import { Lock, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useLogout, useMe, useModelInfo, useSecurityEvents, useSettings, useUpdatePreferences } from "../api/hooks";
import type { Preferences } from "../api/types";
import { Button, Card, ErrorState, Field, LoadingState, PageHeader, inputClass } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { applyTheme } from "../lib/theme";

const EVENT_LABEL: Record<string, string> = {
  login_failure: "Failed sign-in attempt", login_locked: "Sign-in temporarily locked", payment_blocked: "Payment blocked by the risk check",
};

function Toggle({ id, label, description, checked, onChange }: {
  id: string; label: string; description: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="font-medium">{label}</label>
        <p className="text-sm text-slate-600 dark:text-slate-400">{description}</p>
      </div>
      <input id={id} type="checkbox" role="switch" aria-checked={checked} checked={checked}
        onChange={(e) => onChange(e.target.checked)} className="mt-1 size-5 accent-teal-700" />
    </div>
  );
}

export default function SettingsPage() {
  const me = useMe();
  const settings = useSettings();
  const events = useSecurityEvents();
  const model = useModelInfo();
  const update = useUpdatePreferences();
  const logoutAll = useLogout(true);
  const navigate = useNavigate();

  useEffect(() => { if (settings.data) applyTheme(settings.data.preferences.theme); }, [settings.data]);

  if (settings.isPending || me.isPending) return <LoadingState label="Loading settings…" />;
  if (settings.isError) return <ErrorState message={settings.error.message} onRetry={() => settings.refetch()} />;
  const s = settings.data;
  const prefs = s.preferences;
  const setPref = (patch: Partial<Preferences>) => update.mutate(patch);

  return (
    <>
      <PageHeader title="Security and privacy" />
      <div className="grid gap-4 md:grid-cols-2">
        <Card aria-labelledby="profile-title">
          <h2 id="profile-title" className="mb-3 font-semibold">Profile</h2>
          <dl className="flex flex-col gap-2 text-sm">
            {([["Name", me.data?.full_name], ["Email", me.data?.email], ["Mobile", me.data?.phone],
               ["Demo UPI ID", me.data?.upi_id], ["Last sign-in", formatDateTime(me.data?.last_login_at)]] as const).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4"><dt className="text-slate-500">{k}</dt><dd className="break-all text-right font-medium">{v}</dd></div>
            ))}
          </dl>
        </Card>

        <Card aria-labelledby="mode-title">
          <h2 id="mode-title" className="mb-3 flex items-center gap-2 font-semibold"><Lock className="size-4" aria-hidden />Payment mode</h2>
          <p className="text-2xl font-bold">{s.mode === "SIMULATION" ? "Simulation" : s.mode}</p>
          <p className="text-sm text-slate-600 dark:text-slate-400">Payment rail: {s.provider}</p>
          <p className="mt-3 rounded-xl bg-slate-100 p-3 text-sm dark:bg-slate-800">
            Live payments: <strong>{s.live_payments_enabled ? "enabled by the server" : "disabled"}</strong>. {s.live_payments_note}
          </p>
        </Card>

        <Card aria-labelledby="security-title">
          <h2 id="security-title" className="mb-3 font-semibold">Security</h2>
          <ul className="mb-4 list-disc pl-5 text-sm text-slate-700 dark:text-slate-300">
            <li>Your session signs out automatically after a short period.</li>
            <li>Repeated failed sign-ins temporarily lock your account.</li>
            <li>Yogii never asks for your UPI PIN, OTP, card details or bank password.</li>
          </ul>
          <Button variant="secondary" loading={logoutAll.isPending}
            onClick={() => logoutAll.mutate(undefined, { onSettled: () => navigate("/sign-in", { replace: true }) })}>
            Sign out on all devices
          </Button>
          <h3 className="mb-2 mt-5 text-sm font-semibold">Recent security events</h3>
          {events.isPending && <LoadingState />}
          {events.data && events.data.length === 0 && <p className="text-sm text-slate-500">No security events.</p>}
          {events.data && events.data.length > 0 && (
            <ul className="flex flex-col gap-1 text-sm">
              {events.data.slice(0, 6).map((e, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>{EVENT_LABEL[e.event_type] ?? e.event_type}</span>
                  <span className="text-slate-500">{formatDateTime(e.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card aria-labelledby="privacy-title" className="flex flex-col gap-4">
          <h2 id="privacy-title" className="font-semibold">Privacy and display</h2>
          <Toggle id="hide-balance" label="Hide my balance" description="Mask the simulated balance on the dashboard."
            checked={prefs.hide_balance} onChange={(v) => setPref({ hide_balance: v })} />
          <Toggle id="notify-high-risk" label="Highlight high-risk payments" description="Show extra warnings for high-risk simulated payments."
            checked={prefs.notify_on_high_risk} onChange={(v) => setPref({ notify_on_high_risk: v })} />
          <Field id="theme" label="Theme">
            <select id="theme" className={inputClass} value={prefs.theme}
              onChange={(e) => { const t = e.target.value as Preferences["theme"]; applyTheme(t); setPref({ theme: t }); }}>
              <option value="system">Match my device</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </Field>
          <div className="text-sm text-slate-600 dark:text-slate-400">
            <p className="font-medium text-slate-800 dark:text-slate-200">What Yogii keeps</p>
            <p>Your personal details are encrypted. Device and location signals are stored only as keyed hashes. Risk inputs
              are kept for {s.data_retention_days.feature_snapshots} days, security events for {s.data_retention_days.security_events} days
              and transaction-graph links for {s.data_retention_days.transaction_graph_edges} days (prototype defaults).</p>
          </div>
          {update.isError && <p role="alert" className="text-sm text-red-700">{update.error.message}</p>}
        </Card>

        <Card aria-labelledby="risk-title-settings" className="md:col-span-2">
          <h2 id="risk-title-settings" className="mb-3 flex items-center gap-2 font-semibold"><ShieldCheck className="size-4" aria-hidden />How the risk check works</h2>
          <dl className="mb-3 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(s.risk_bands).map(([band, text]) => (
              <div key={band} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/60"><dt className="font-semibold">{band.replace("_", " ")}</dt><dd>{text}</dd></div>
            ))}
          </dl>
          <p className="text-sm text-slate-600 dark:text-slate-400">{s.thresholds_note} Looks back {s.history_window_days} days of your
            history and up to {s.graph_depth} transfers in the transaction graph. Graph patterns are signals, never proof on their own.</p>
          {model.data && <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">Model {model.data.model_version}. {model.data.disclaimer}</p>}
        </Card>
      </div>
    </>
  );
}
