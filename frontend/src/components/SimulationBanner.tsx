import { ShieldAlert } from "lucide-react";

/** Shown on every screen. Yogii has no connection to UPI, NPCI or any bank. */
export default function SimulationBanner() {
  return (
    <div role="note" aria-label="Simulation notice"
      className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
      <ShieldAlert className="mr-1.5 inline size-4 -translate-y-px" aria-hidden />
      <strong>Simulation mode.</strong> Balances, accounts and payments are simulated. No real money moves, and Yogii
      is not connected to UPI, NPCI or any bank.
    </div>
  );
}
