import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useRegister } from "../api/hooks";
import { Button, Card, Field, inputClass } from "../components/ui";
import AuthShell from "./AuthShell";

type Form = { full_name: string; email: string; phone: string; upi_handle: string; password: string; confirm: string };
type Errors = Partial<Record<keyof Form, string>>;

export function validateRegistration(f: Form): Errors {
  const e: Errors = {};
  if (!/^[A-Za-z][A-Za-z .'-]{1,79}$/.test(f.full_name.trim())) e.full_name = "Enter your name using letters and spaces.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(f.email.trim())) e.email = "Enter a valid email address.";
  if (!/^[6-9][0-9]{9}$/.test(f.phone.replace(/[\s-]/g, "").replace(/^\+91/, ""))) e.phone = "Enter a 10-digit Indian mobile number.";
  if (!/^[a-z0-9][a-z0-9._-]{1,40}$/.test(f.upi_handle.trim().toLowerCase())) e.upi_handle = "Use 2-40 letters, numbers, dots, dashes or underscores.";
  if (f.password.length < 10 || !/[a-z]/.test(f.password) || !/[A-Z]/.test(f.password) || !/[0-9]/.test(f.password))
    e.password = "Use at least 10 characters with uppercase, lowercase and a number.";
  if (f.confirm !== f.password) e.confirm = "Passwords don't match.";
  return e;
}

const FIELD_MAP: Record<string, keyof Form> = { full_name: "full_name", email: "email", phone: "phone", upi_id: "upi_handle", password: "password" };

export default function RegisterPage() {
  const [form, setForm] = useState<Form>({ full_name: "", email: "", phone: "", upi_handle: "", password: "", confirm: "" });
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState("");
  const register = useRegister();
  const navigate = useNavigate();
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    const found = validateRegistration(form);
    setErrors(found);
    if (Object.keys(found).length) {
      document.getElementById(Object.keys(found)[0])?.focus();
      return;
    }
    register.mutate({
      full_name: form.full_name.trim(), email: form.email.trim(), phone: form.phone,
      upi_id: `${form.upi_handle.trim().toLowerCase()}@yogii`, password: form.password,
    }, {
      onSuccess: () => navigate("/", { replace: true }),
      onError: (err) => {
        if (err instanceof ApiError && err.fieldErrors.length) {
          const mapped: Errors = {};
          for (const fe of err.fieldErrors) if (FIELD_MAP[fe.field]) mapped[FIELD_MAP[fe.field]] = fe.message.replace(/^Value error, /, "");
          setErrors(mapped);
        }
        setFormError(err instanceof ApiError ? err.message : "Registration failed. Please try again.");
      },
    });
  };

  const input = (k: keyof Form, type = "text", autoComplete?: string) => (
    <input id={k} type={type} className={inputClass} value={form[k]} onChange={set(k)} autoComplete={autoComplete}
      aria-invalid={Boolean(errors[k]) || undefined} aria-describedby={errors[k] ? `${k}-error` : `${k}-hint`} />
  );

  return (
    <AuthShell title="Create a demo account" subtitle="You'll get a simulated balance to try payments. No real money is involved.">
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field id="full_name" label="Full name" error={errors.full_name}>{input("full_name", "text", "name")}</Field>
          <Field id="email" label="Email" error={errors.email}>{input("email", "email", "email")}</Field>
          <Field id="phone" label="Mobile number" hint="10 digits, for example 98765 43210" error={errors.phone}>
            {input("phone", "tel", "tel-national")}
          </Field>
          <Field id="upi_handle" label="Demo UPI ID" hint="Demo UPI IDs always end in @yogii" error={errors.upi_handle}>
            <div className="flex items-center gap-2">
              {input("upi_handle", "text", "off")}
              <span className="font-mono text-slate-600 dark:text-slate-300">@yogii</span>
            </div>
          </Field>
          <Field id="password" label="Password" hint="At least 10 characters with uppercase, lowercase and a number" error={errors.password}>
            {input("password", "password", "new-password")}
          </Field>
          <Field id="confirm" label="Confirm password" error={errors.confirm}>{input("confirm", "password", "new-password")}</Field>
          <div aria-live="assertive">{formError && <p role="alert" className="text-sm font-medium text-red-700 dark:text-red-400">{formError}</p>}</div>
          <Button type="submit" loading={register.isPending}>Create account</Button>
          <p className="text-center text-sm text-slate-600 dark:text-slate-400">
            Already have an account? <Link to="/sign-in" className="font-semibold text-teal-700 underline dark:text-teal-400">Sign in</Link>
          </p>
        </form>
      </Card>
    </AuthShell>
  );
}
