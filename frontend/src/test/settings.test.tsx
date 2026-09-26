import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SettingsPage from "../pages/SettingsPage";
import { mockApi, renderApp } from "./utils";

const settings = {
  mode: "SIMULATION", live_payments_enabled: false,
  live_payments_note: "Live payments are disabled. They can only be enabled by the server deployment.",
  provider: "MockPaymentProvider", risk_policy_version: "v1",
  risk_bands: { LOW: "0-29", MEDIUM: "30-59", HIGH: "60-84", VERY_HIGH: "85-100" },
  thresholds_note: "Yogii prototype thresholds. Not RBI, NPCI or bank standards.", max_payment_amount: 100000,
  history_window_days: 30, graph_depth: 2,
  data_retention_days: { feature_snapshots: 180, security_events: 365, transaction_graph_edges: 90 },
  preferences: { hide_balance: false, notify_on_high_risk: true, theme: "system" },
};

describe("settings", () => {
  it("shows simulation mode read-only, with no control that could enable live payments", async () => {
    mockApi({
      "GET /api/settings": { body: settings },
      "GET /api/me": { body: { full_name: "Asha Rao", email: "a@b.co", phone: "9812345678", upi_id: "asha@yogii", last_login_at: null } },
      "GET /api/me/security-events": { body: [{ event_type: "login_failure", severity: "MEDIUM", created_at: "2026-01-01T00:00:00Z" }] },
      "GET /api/model/info": { body: { model_version: "2.0.0-synthetic", disclaimer: "Synthetic data only." } },
    });
    renderApp(<SettingsPage />);
    expect(await screen.findByText("Simulation")).toBeInTheDocument();
    expect(screen.getByText(/Live payments:/)).toHaveTextContent("disabled");
    const switches = screen.getAllByRole("switch").map((s) => s.getAttribute("id"));
    expect(switches).toEqual(["hide-balance", "notify-high-risk"]);
    expect(screen.queryByLabelText(/live/i)).not.toBeInTheDocument();
    expect(screen.getByText("Failed sign-in attempt")).toBeInTheDocument();
  });
});
