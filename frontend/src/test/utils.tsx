import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

export interface Call { method: string; path: string; headers: Record<string, string>; body: unknown }
type Handler = (call: Call) => { status?: number; body: unknown };

/** Replace fetch with a tiny router: keys look like "GET /api/me" or "POST /api/payments/assess". */
export function mockApi(routes: Record<string, Handler | { status?: number; body: unknown }>) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = {
      method, path: url.pathname + url.search, headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const key = Object.keys(routes).find((k) => k === `${method} ${url.pathname}${url.search}`) ??
      Object.keys(routes).find((k) => k === `${method} ${url.pathname}`);
    if (!key) return new Response(JSON.stringify({ detail: `No mock for ${method} ${url.pathname}` }), { status: 500 });
    const route = routes[key];
    const res = typeof route === "function" ? route(call) : route;
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

export function renderApp(ui: ReactElement, { route = "/under-test", path = "/under-test" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="/sign-in" element={<p>sign-in page</p>} />
          <Route path="/" element={<p>home page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const risk = (band: "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH", score: number, codes: string[] = []) => ({
  score, band, decision: band === "VERY_HIGH" ? "BLOCK" : band === "LOW" ? "ALLOW" : "VERIFY",
  requires_verification: band === "MEDIUM" || band === "HIGH", blocked: band === "VERY_HIGH",
  reason_codes: codes.map((code) => ({ code, description: `Reason ${code.toLowerCase()}` })),
  score_kind: "calibrated_probability_synthetic", model_version: "2.0.0-synthetic",
  policy_version: "yogii-prototype-policy-v1", assessed_at: "2026-01-01T10:00:00Z",
});

export function payment(over: Record<string, unknown> = {}) {
  return {
    id: 7, reference: "YOGII-SIM-ABC", mode: "SIMULATION", is_simulated: true, direction: "outgoing",
    state: "ASSESSING", amount: "18000.00", currency: "INR",
    recipient: { name: "Unverified UPI ID", upi_id: "arjun@okaxis", payment_type: "P2P" },
    note: null, failure_reason: null, simulated_outcome: null, provider: "MockPaymentProvider",
    created_at: "2026-01-01T10:00:00Z", updated_at: "2026-01-01T10:00:00Z", completed_at: null,
    risk: risk("LOW", 5),
    actions: { can_authorize: true, needs_verification: false, can_cancel: true, can_refresh_status: false },
    timeline: [], ...over,
  };
}
