import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import RegisterPage, { validateRegistration } from "../pages/RegisterPage";
import SignInPage from "../pages/SignInPage";
import { mockApi, renderApp } from "./utils";

describe("sign in", () => {
  it("shows the server's generic error and keeps the user on the form", async () => {
    mockApi({ "POST /api/auth/login": { status: 401, body: { detail: "The details you entered don't match an account." } } });
    renderApp(<SignInPage />, { route: "/login", path: "/login" });
    await userEvent.type(screen.getByLabelText(/email, mobile number or upi id/i), "yogesh@yogii");
    await userEvent.type(screen.getByLabelText(/^password$/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match an account");
  });

  it("goes home after a successful sign-in", async () => {
    mockApi({ "POST /api/auth/login": { body: { user: {}, csrf_token: "x", expires_at: "", mode: "SIMULATION" } } });
    renderApp(<SignInPage />, { route: "/login", path: "/login" });
    await userEvent.type(screen.getByLabelText(/email, mobile number or upi id/i), "yogesh@yogii");
    await userEvent.type(screen.getByLabelText(/^password$/i), "Password123!");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});

describe("registration", () => {
  it("validates before calling the API", async () => {
    const calls = mockApi({});
    renderApp(<RegisterPage />, { route: "/register", path: "/register" });
    await userEvent.type(screen.getByLabelText(/full name/i), "Asha Rao");
    await userEvent.type(screen.getByLabelText(/^email$/i), "asha@example.com");
    await userEvent.type(screen.getByLabelText(/mobile number/i), "12345");
    await userEvent.type(screen.getByLabelText(/demo upi id/i), "asha");
    await userEvent.type(screen.getByLabelText(/^password$/i), "weak");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "weak");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByText(/10-digit Indian mobile number/)).toBeInTheDocument();
    expect(screen.getByText(/at least 10 characters/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("maps server field errors back onto the form", async () => {
    mockApi({ "POST /api/auth/register": { status: 422, body: { detail: "Please check the highlighted fields.",
      errors: [{ field: "email", message: "Value error, Enter a valid email address." }] } } });
    renderApp(<RegisterPage />, { route: "/register", path: "/register" });
    await userEvent.type(screen.getByLabelText(/full name/i), "Asha Rao");
    await userEvent.type(screen.getByLabelText(/^email$/i), "asha@example.co");
    await userEvent.type(screen.getByLabelText(/mobile number/i), "9812345678");
    await userEvent.type(screen.getByLabelText(/demo upi id/i), "asha");
    await userEvent.type(screen.getByLabelText(/^password$/i), "StrongPass123");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "StrongPass123");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument());
  });

  it("validation rules match the backend", () => {
    const ok = { full_name: "Asha Rao", email: "a@b.co", phone: "+91 98123 45678", upi_handle: "asha.r", password: "StrongPass1", confirm: "StrongPass1" };
    expect(validateRegistration(ok)).toEqual({});
    expect(validateRegistration({ ...ok, phone: "5812345678" }).phone).toBeDefined();
    expect(validateRegistration({ ...ok, confirm: "x" }).confirm).toBeDefined();
  });
});
