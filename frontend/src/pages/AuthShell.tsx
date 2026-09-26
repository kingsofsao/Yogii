import type { ReactNode } from "react";
import SimulationBanner from "../components/SimulationBanner";

export default function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <SimulationBanner />
      <main className="mx-auto flex max-w-md flex-col gap-6 px-4 py-10">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-teal-700 text-xl font-bold text-white">Y</span>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="text-slate-600 dark:text-slate-400">{subtitle}</p>
        </div>
        {children}
      </main>
    </div>
  );
}
