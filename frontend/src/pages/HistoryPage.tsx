import { useState } from "react";
import { Link } from "react-router-dom";
import { usePayments } from "../api/hooks";
import PaymentRow from "../components/PaymentRow";
import { Button, Card, EmptyState, ErrorState, Field, LoadingState, PageHeader, inputClass } from "../components/ui";

const STATES = ["", "COMPLETED", "PENDING", "NEEDS_VERIFICATION", "ASSESSING", "BLOCKED", "FAILED", "REVERSED"];
const BANDS = ["", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"];
const label = (s: string) => (s ? s.charAt(0) + s.slice(1).toLowerCase().replace("_", " ") : "All");

export default function HistoryPage() {
  const [state, setState] = useState("");
  const [band, setBand] = useState("");
  const [limit, setLimit] = useState(20);
  const q = usePayments({ state: state || undefined, band: band || undefined, limit });

  return (
    <>
      <PageHeader title="Payment history" subtitle="Every attempt is kept, including blocked, cancelled and failed ones." />
      <Card className="mb-4">
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()} aria-label="Filter payments">
          <Field id="filter-state" label="Status">
            <select id="filter-state" className={inputClass} value={state} onChange={(e) => { setState(e.target.value); setLimit(20); }}>
              {STATES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </select>
          </Field>
          <Field id="filter-band" label="Risk level">
            <select id="filter-band" className={inputClass} value={band} onChange={(e) => { setBand(e.target.value); setLimit(20); }}>
              {BANDS.map((b) => <option key={b} value={b}>{label(b)}</option>)}
            </select>
          </Field>
        </form>
      </Card>
      <Card>
        {q.isPending && <LoadingState label="Loading payments…" />}
        {q.isError && <ErrorState message={q.error.message} onRetry={() => q.refetch()} />}
        {q.data && q.data.items.length === 0 && (
          <EmptyState title={state || band ? "No payments match these filters" : "No payments yet"}
            action={<Link to="/send" className="text-sm font-semibold text-teal-700 underline">Send money</Link>} />
        )}
        {q.data && q.data.items.length > 0 && (
          <>
            <p className="mb-2 text-sm text-slate-500" aria-live="polite">{q.data.total} payment{q.data.total === 1 ? "" : "s"}</p>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">{q.data.items.map((p) => <PaymentRow key={p.id} p={p} />)}</ul>
            {q.data.total > q.data.items.length && (
              <div className="mt-4 flex justify-center">
                <Button variant="secondary" loading={q.isFetching} onClick={() => setLimit(limit + 20)}>Show more</Button>
              </div>
            )}
          </>
        )}
      </Card>
    </>
  );
}
