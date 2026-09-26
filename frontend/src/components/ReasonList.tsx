import { Info } from "lucide-react";
import type { ReasonCode } from "../api/types";

export default function ReasonList({ reasons }: { reasons: ReasonCode[] }) {
  if (reasons.length === 0) {
    return <p className="text-sm text-slate-600 dark:text-slate-400">Nothing unusual stood out.</p>;
  }
  return (
    <ul className="flex flex-col gap-2" aria-label="Why this risk level">
      {reasons.map((r) => (
        <li key={r.code} className="flex gap-2 text-sm text-slate-800 dark:text-slate-200" data-code={r.code}>
          <Info className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden />
          <span>{r.description}</span>
        </li>
      ))}
    </ul>
  );
}
