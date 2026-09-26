import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import SendPage from "../pages/SendPage";
import { mockApi, payment, renderApp, risk } from "./utils";

const recipient = { name: "Unverified UPI ID", upi_id: "arjun@okaxis", payment_type: "P2P", kind: "unverified",
  merchant_category: null, is_fictional_demo: true, notice: "This UPI ID isn't in the Yogii demo directory." };
const base = {
  "GET /api/recipients": { body: [] },
  "GET /api/dashboard": { body: { simulated_balance: "50000.00" } },
  "GET /api/recipients/lookup": { body: recipient },
};

async function reachAmount() {
  await userEvent.type(screen.getByLabelText(/upi id or mobile number/i), "arjun@okaxis");
  await userEvent.click(screen.getByRole("button", { name: /find recipient/i }));
  expect(await screen.findByRole("note")).toHaveTextContent(/isn't in the Yogii demo directory/);
  await userEvent.click(screen.getByRole("button", { name: /yes, pay this recipient/i }));
  await userEvent.type(screen.getByLabelText(/amount/i), "18000");
}

describe("send money", () => {
  it("requires every verification check before authorising a MEDIUM/HIGH payment", async () => {
    const assessed = payment({ state: "NEEDS_VERIFICATION", risk: risk("HIGH", 67, ["AMOUNT_ABOVE_USUAL", "NEW_RECIPIENT"]),
      actions: { can_authorize: true, needs_verification: true, can_cancel: true, can_refresh_status: false } });
    const calls = mockApi({
      ...base,
      "GET /api/recipients/lookup?q=arjun%40okaxis": { body: recipient },
      "POST /api/payments/assess": { status: 201, body: assessed },
      "POST /api/payments": { body: payment({ state: "COMPLETED", risk: assessed.risk }) },
    });
    renderApp(<SendPage />);
    await reachAmount();
    await userEvent.selectOptions(screen.getByLabelText(/simulated device/i), "new-phone");
    await userEvent.click(screen.getByRole("button", { name: /check risk/i }));

    expect(await screen.findByTestId("risk-score")).toHaveTextContent("67");
    const authorise = screen.getByRole("button", { name: /authorise simulated payment/i });
    expect(authorise).toBeDisabled();
    for (const box of within(screen.getByRole("group", { name: /demo verification/i })).getAllByRole("checkbox")) {
      await userEvent.click(box);
    }
    expect(authorise).toBeEnabled();
    await userEvent.click(authorise);
    expect(await screen.findByText("Payment completed")).toBeInTheDocument();

    const assess = calls.find((c) => c.path === "/api/payments/assess")!;
    expect(assess.headers["Idempotency-Key"]).toMatch(/^web-/);
    expect(assess.body).toMatchObject({ recipient_upi: "arjun@okaxis", amount: 18000, simulated_context: { device: "new-phone" } });
    const auth = calls.find((c) => c.path === "/api/payments" && c.method === "POST")!;
    expect(auth.body).toMatchObject({ payment_id: 7, demo_verification_confirmed: true, simulated_outcome: "SUCCESS" });
    // No request ever carries a PIN or OTP field.
    expect(JSON.stringify(calls.map((c) => c.body))).not.toMatch(/pin|otp/i);
  });

  it("shows a blocked result with no way to authorise", async () => {
    const blocked = payment({ state: "BLOCKED", risk: risk("VERY_HIGH", 96, ["RECEIVER_RISK_SIGNAL"]),
      actions: { can_authorize: false, needs_verification: false, can_cancel: false, can_refresh_status: false } });
    mockApi({ ...base, "GET /api/recipients/lookup?q=arjun%40okaxis": { body: recipient },
      "POST /api/payments/assess": { status: 201, body: blocked } });
    renderApp(<SendPage />);
    await reachAmount();
    await userEvent.click(screen.getByRole("button", { name: /check risk/i }));
    expect(await screen.findByText("This payment was blocked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /authorise/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /see result/i }));
    expect(screen.getByRole("heading", { name: "Payment blocked" })).toBeInTheDocument();
  });

  it("rejects amounts above the balance before calling the API", async () => {
    const calls = mockApi({ ...base, "GET /api/recipients/lookup?q=arjun%40okaxis": { body: recipient } });
    renderApp(<SendPage />);
    await userEvent.type(screen.getByLabelText(/upi id or mobile number/i), "arjun@okaxis");
    await userEvent.click(screen.getByRole("button", { name: /find recipient/i }));
    await userEvent.click(await screen.findByRole("button", { name: /yes, pay this recipient/i }));
    await userEvent.type(screen.getByLabelText(/amount/i), "60000");
    await userEvent.click(screen.getByRole("button", { name: /check risk/i }));
    expect(screen.getByText(/more than your simulated balance/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/payments/assess")).toBe(false);
  });

  it("shows lookup errors", async () => {
    mockApi({ ...base, "GET /api/recipients/lookup?q=9000000000": { status: 404, body: { detail: "No demo payee uses this mobile number." } } });
    renderApp(<SendPage />);
    await userEvent.type(screen.getByLabelText(/upi id or mobile number/i), "9000000000");
    await userEvent.click(screen.getByRole("button", { name: /find recipient/i }));
    expect(await screen.findByText(/No demo payee uses this mobile number/)).toBeInTheDocument();
  });
});
