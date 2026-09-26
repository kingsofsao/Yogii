import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useCancelPayment, usePayment, useRefreshStatus } from "../api/hooks";
import Money from "../components/Money";
import RiskCard from "../components/RiskCard";
import { Button, Card, ErrorState, LoadingState, PageHeader, SimTag, StateBadge } from "../components/ui";
import { formatDateTime } from "../lib/format";

export default function PaymentDetailPage() {
  const id = Number(useParams().id);
  const q = usePayment(id);
  const refresh = useRefreshStatus();
  const cancel = useCancelPayment();

  if (!Number.isFinite(id)) return <ErrorState message="That payment link isn't valid." />;
  if (q.isPending) return <LoadingState label="Loading payment…" />;
  if (q.isError) return <ErrorState message={q.error instanceof ApiError && q.error.status === 404 ? "Payment not found." : q.error.message} onRetry={() => q.refetch()} />;
  const p = q.data;

  return (
    <div className="mx-auto max-w-2xl">
      <Link to="/history" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-teal-700 underline dark:text-teal-400">
        <ArrowLeft className="size-4" aria-hidden /> Payment history
      </Link>
      <PageHeader title={`Payment to ${p.recipient.name}`} />
      <div className="flex flex-col gap-4">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Money amount={p.amount} className="text-3xl font-bold tabular-nums" />
            <div className="flex gap-2"><StateBadge state={p.state} />{p.is_simulated && <SimTag />}</div>
          </div>
          <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {([
              ["Recipient", `${p.recipient.name} (${p.recipient.upi_id})`],
              ["Type", p.recipient.payment_type === "P2M" ? "Person to merchant (P2M)" : "Person to person (P2P)"],
              ["Reference", p.reference],
              ["Payment rail", `${p.provider}${p.is_simulated ? " (simulated)" : ""}`],
              ["Created", formatDateTime(p.created_at)],
              ["Completed", formatDateTime(p.completed_at)],
              ...(p.note ? [["Note", p.note]] : []),
              ...(p.failure_reason ? [["Reason", p.failure_reason]] : []),
            ] as [string, string][]).map(([k, v]) => (
              <div key={k}><dt className="text-slate-500">{k}</dt><dd className="break-words font-medium">{v}</dd></div>
            ))}
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {p.actions.can_refresh_status && (
              <Button onClick={() => refresh.mutate(p.id)} loading={refresh.isPending}>Check status</Button>
            )}
            {p.actions.can_cancel && (
              <Button variant="secondary" onClick={() => cancel.mutate(p.id)} loading={cancel.isPending}>Cancel payment</Button>
            )}
          </div>
        </Card>
        {p.risk && <RiskCard risk={p.risk} title="Risk assessment at the time of payment" />}
        {p.timeline && (
          <Card aria-labelledby="timeline-title">
            <h2 id="timeline-title" className="mb-3 font-semibold">Timeline</h2>
            <ol className="flex flex-col gap-3 border-l-2 border-slate-200 pl-4 dark:border-slate-700">
              {p.timeline.map((t, i) => (
                <li key={i} className="text-sm">
                  <p className="font-semibold">{t.state.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())}</p>
                  {t.reason && <p className="text-slate-600 dark:text-slate-400">{t.reason}</p>}
                  <p className="text-xs text-slate-500">{formatDateTime(t.at)}</p>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </div>
    </div>
  );
}
