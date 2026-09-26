import { describe, expect, it, vi } from "vitest";
import { api, ApiError, UNAUTHORIZED_EVENT } from "../api/client";
import { mockApi } from "./utils";

describe("api client", () => {
  it("sends the CSRF cookie and idempotency key on state-changing requests", async () => {
    document.cookie = "yogii_csrf=csrf-abc; path=/";
    const calls = mockApi({ "POST /api/payments/assess": { status: 201, body: { ok: true } } });
    await api("/payments/assess", { method: "POST", body: { amount: 1 }, idempotencyKey: "key-123456" });
    expect(calls[0].headers["X-CSRF-Token"]).toBe("csrf-abc");
    expect(calls[0].headers["Idempotency-Key"]).toBe("key-123456");
  });

  it("does not send the CSRF token on GET", async () => {
    document.cookie = "yogii_csrf=csrf-abc; path=/";
    const calls = mockApi({ "GET /api/me": { body: {} } });
    await api("/me");
    expect(calls[0].headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("turns error responses into ApiError with code and field errors", async () => {
    mockApi({ "POST /api/auth/register": { status: 422, body: { detail: "Please check", code: "invalid_input", errors: [{ field: "phone", message: "bad" }] } } });
    const err = (await api("/auth/register", { method: "POST", body: {} }).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("invalid_input");
    expect(err.fieldErrors[0].field).toBe("phone");
  });

  it("announces 401s outside the auth endpoints so the app can return to sign-in", async () => {
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);
    mockApi({ "GET /api/dashboard": { status: 401, body: { detail: "Please sign in." } } });
    await api("/dashboard").catch(() => undefined);
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });
});
