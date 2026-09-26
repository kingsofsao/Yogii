import { History, Home, LogOut, Send, Settings as SettingsIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useLogout, useMe } from "../api/hooks";
import SimulationBanner from "./SimulationBanner";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/send", label: "Send", icon: Send },
  { to: "/history", label: "History", icon: History },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Layout() {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const location = useLocation();
  const main = useRef<HTMLElement>(null);

  // Move focus to the page heading on navigation so screen readers announce the new page.
  useEffect(() => {
    main.current?.querySelector<HTMLElement>("h1")?.focus();
  }, [location.pathname]);

  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate("/sign-in", { replace: true }) });

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-teal-700 focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <SimulationBanner />
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2 font-bold" aria-label="Yogii home">
            <span className="grid size-8 place-items-center rounded-lg bg-teal-700 text-white">Y</span>
            Yogii
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800 dark:bg-amber-900 dark:text-amber-200">
              Simulation
            </span>
          </NavLink>
          <nav aria-label="Main" className="hidden gap-1 md:flex">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}
                className={({ isActive }) => cx("flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium",
                  isActive ? "bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800")}>
                <Icon className="size-4" aria-hidden />{label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <span className="hidden text-sm text-slate-600 sm:inline dark:text-slate-300">{me.data?.full_name}</span>
            <button onClick={signOut} className="flex min-h-11 items-center gap-1 rounded-lg px-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
              <LogOut className="size-4" aria-hidden /> Sign out
            </button>
          </div>
        </div>
      </header>
      <main id="main" ref={main} className="mx-auto max-w-5xl px-4 pb-28 pt-6 md:pb-12">
        <Outlet />
      </main>
      <nav aria-label="Main (mobile)" className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white md:hidden dark:border-slate-800 dark:bg-slate-900">
        <ul className="grid grid-cols-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink to={to} end={end}
                className={({ isActive }) => cx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium",
                  isActive ? "text-teal-700 dark:text-teal-300" : "text-slate-500")}>
                <Icon className="size-5" aria-hidden />{label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
