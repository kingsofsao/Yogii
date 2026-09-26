import { ChevronRight, Store, User } from "lucide-react";
import { Link } from "react-router-dom";
import type { Payment } from "../api/types";
import { formatDateTime } from "../lib/format";
import Money from "./Money";
import { RiskBadge, StateBadge } from "./ui";

export default function PaymentRow({ p }: { p: Payment }) {
  const Icon = p.recipient.payment_type === "P2M" ? Store : User;
  return (
    <li>
      <Link to={`/payments/${p.id}`}
        className="flex items-center gap-3 rounded-xl px-2 py-3 hover:bg-slate-50 focus-visible:outline-3 focus-visible:outline-teal-600 dark:hover:bg-slate-800/60">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300">
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{p.recipient.name}</span>
          <span className="block truncate text-xs text-slate-500">{p.recipient.upi_id} · {formatDateTime(p.created_at)}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <Money amount={p.amount} className="font-semibold tabular-nums" />
          <span className="flex flex-wrap justify-end gap-1">
            <StateBadge state={p.state} />
            {p.risk && p.risk.band !== "LOW" && <span className="hidden sm:inline-flex"><RiskBadge band={p.risk.band} /></span>}
          </span>
        </span>
        <ChevronRight className="size-4 text-slate-400" aria-hidden />
      </Link>
    </li>
  );
}
