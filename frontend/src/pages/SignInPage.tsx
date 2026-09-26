import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useLogin } from "../api/hooks";
import { Button, Card, Field, inputClass } from "../components/ui";
import AuthShell from "./AuthShell";

const DEMO = ["yogesh@demo.yogii", "visrojit@demo.yogii", "dinesh@demo.yogii"];

export default function SignInPage() {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { from?: string; expired?: boolean } | null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!identifier.trim() || !password) {
      setError("Enter your email, mobile number or UPI ID, and your password.");
      return;
    }
    login.mutate({ identifier: identifier.trim(), password }, {
      onSuccess: () => navigate(state?.from && state.from !== "/sign-in" ? state.from : "/", { replace: true }),
      onError: (err) => setError(err instanceof ApiError ? err.message : "Sign-in failed. Please try again."),
    });
  };

  return (
    <AuthShell title="Sign in to Yogii" subtitle="Simulated payments with a fraud-risk check before you pay.">
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          {state?.expired && <p role="status" className="rounded-lg bg-slate-100 p-2 text-sm dark:bg-slate-800">Your session ended. Please sign in again.</p>}
          <Field id="identifier" label="Email, mobile number or UPI ID">
            <input id="identifier" className={inputClass} autoComplete="username" value={identifier}
              onChange={(e) => setIdentifier(e.target.value)} aria-invalid={Boolean(error) || undefined} autoFocus />
          </Field>
          <Field id="password" label="Password">
            <input id="password" type="password" className={inputClass} autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} aria-invalid={Boolean(error) || undefined} />
          </Field>
          <div aria-live="assertive">{error && <p role="alert" className="text-sm font-medium text-red-700 dark:text-red-400">{error}</p>}</div>
          <Button type="submit" loading={login.isPending}>Sign in</Button>
          <p className="text-center text-sm text-slate-600 dark:text-slate-400">
            New to Yogii? <Link to="/register" className="font-semibold text-teal-700 underline dark:text-teal-400">Create a demo account</Link>
          </p>
        </form>
      </Card>
      <Card className="text-sm">
        <h2 className="mb-2 font-semibold">Fictional demo accounts</h2>
        <ul className="mb-2 flex flex-col gap-1">
          {DEMO.map((d) => (
            <li key={d}>
              <button type="button" className="font-mono text-teal-700 underline dark:text-teal-400" onClick={() => setIdentifier(d)}>{d}</button>
            </li>
          ))}
        </ul>
        <p className="text-slate-600 dark:text-slate-400">Password: <span className="font-mono">Password123!</span>. Run the seed script first.</p>
        <p className="mt-2 text-slate-600 dark:text-slate-400">Yogii never asks for your UPI PIN, OTP, card details or bank password.</p>
      </Card>
    </AuthShell>
  );
}
