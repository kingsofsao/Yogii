import type { Risk } from "../api/types";
import { BAND_GUIDANCE } from "../lib/format";
import ReasonList from "./ReasonList";
import { Card, RiskBadge, cx } from "./ui";

const bar: Record<Risk["band"], string> = {
  LOW: "bg-emerald-600", MEDIUM: "bg-amber-500", HIGH: "bg-orange-600", VERY_HIGH: "bg-red-700",
};

/** Score, band, plain-language guidance and safe reason codes. Never internal rules or thresholds per feature. */
export default function RiskCard({ risk, title = "Risk check" }: { risk: Risk; title?: string }) {
  const guide = BAND_GUIDANCE[risk.band];
  return (
    <Card aria-labelledby="risk-title" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="risk-title" className="text-lg font-semibold">{title}</h2>
        <RiskBadge band={risk.band} />
      </div>
      <div>
        <div className="flex items-baseline gap-1">
          <span className="text-4xl font-bold tabular-nums" data-testid="risk-score">{risk.score}</span>
          <span className="text-slate-500">/ 100</span>
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="img"
          aria-label={`Risk score ${risk.score} out of 100`}>
          <div className={cx("h-full rounded-full", bar[risk.band])} style={{ width: `${Math.max(3, risk.score)}%` }} />
        </div>
      </div>
      <div className={cx("rounded-xl p-3", risk.band === "LOW" ? "bg-emerald-50 dark:bg-emerald-950/50" : risk.band === "VERY_HIGH" ? "bg-red-50 dark:bg-red-950/50" : "bg-amber-50 dark:bg-amber-950/50")}>
        <p className="font-semibold">{guide.title}</p>
        <p className="text-sm text-slate-700 dark:text-slate-300">{guide.body}</p>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">What we noticed</h3>
        <ReasonList reasons={risk.reason_codes} />
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Prototype model trained on synthetic data (v{risk.model_version}). Scores are signals, not proof that a person
        or payment is fraudulent. Thresholds are Yogii prototype values, not RBI, NPCI or bank standards.
      </p>
    </Card>
  );
}
