import { ArrowDownLeft, Eye, EyeOff, Send } from "lucide-react";
import { Link } from "react-router-dom";
import { useDashboard, useUpdatePreferences } from "../api/hooks";
import Money from "../components/Money";
import PaymentRow from "../components/PaymentRow";
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, SimTag } from "../components/ui";
import { formatDateTime } from "../lib/format";

export default function DashboardPage() {
  const q = useDashboard();
  const prefs = useUpdatePreferences();
  if (q.isPending) return <LoadingState label="Loading your dashboard…" />;
  if (q.isError) return <ErrorState message={q.error.message} onRetry={() => q.refetch()} />;
  const d = q.data;

  return (
    <>
      <PageHeader title={`Hello, ${d.user.full_name.split(" ")[0]}`} subtitle="Here's your simulated account." />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2" aria-labelledby="balance-title">
          <div className="flex items-center justify-between">
            <h2 id="balance-title" className="text-sm font-semibold text-slate-600 dark:text-slate-400">Simulated balance</h2>
            <SimTag />
          </div>
          <p className="mt-2 text-4xl font-bold tabular-nums" aria-live="polite">
            <Money amount={d.simulated_balance} hidden={d.hide_balance} />
          </p>
          <p className="mt-1 font-mono text-sm text-slate-500">{d.user.upi_id}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to="/send" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 dark:bg-teal-500 dark:text-slate-950">
              <Send className="size-4" aria-hidden /> Send money
            </Link>
            <Button variant="secondary" loading={prefs.isPending} aria-pressed={d.hide_balance}
              onClick={() => prefs.mutate({ hide_balance: !d.hide_balance })}>
              {d.hide_balance ? <Eye className="size-4" aria-hidden /> : <EyeOff className="size-4" aria-hidden />}
              {d.hide_balance ? "Show balance" : "Hide balance"}
            </Button>
          </div>
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">{d.notice}</p>
        </Card>
        <Card aria-labelledby="stats-title">
          <h2 id="stats-title" className="mb-3 text-sm font-semibold text-slate-600 dark:text-slate-400">Your payments</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {([["Completed", d.stats.completed], ["Blocked", d.stats.blocked], ["Failed", d.stats.failed],
               ["Pending", d.stats.pending]] as const).map(([label, n]) => (
              <div key={label} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/60">
                <dt className="text-slate-500">{label}</dt>
                <dd className="text-xl font-bold tabular-nums">{n}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2" aria-labelledby="recent-title">
          <div className="mb-2 flex items-center justify-between">
            <h2 id="recent-title" className="font-semibold">Recent payments</h2>
            <Link to="/history" className="text-sm font-semibold text-teal-700 underline dark:text-teal-400">View all</Link>
          </div>
          {d.recent_payments.length === 0 ? (
            <EmptyState title="No payments yet" body="Your simulated payments will appear here."
              action={<Link to="/send" className="text-sm font-semibold text-teal-700 underline">Make your first payment</Link>} />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">{d.recent_payments.map((p) => <PaymentRow key={p.id} p={p} />)}</ul>
          )}
        </Card>
        <Card aria-labelledby="incoming-title">
          <h2 id="incoming-title" className="mb-2 font-semibold">Money received</h2>
          {d.recent_incoming.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing received yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {d.recent_incoming.map((i) => (
                <li key={i.id} className="flex items-center gap-3">
                  <ArrowDownLeft className="size-5 text-emerald-600" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{i.from_name}</span>
                    <span className="block text-xs text-slate-500">{formatDateTime(i.created_at)}</span>
                  </span>
                  <Money amount={i.amount} className="text-sm font-semibold tabular-nums text-emerald-700 dark:text-emerald-400" />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
