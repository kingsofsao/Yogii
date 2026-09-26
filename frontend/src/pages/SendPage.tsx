import { ArrowLeft, BadgeCheck, CheckCircle2, Clock, Search, ShieldAlert, Store, User, XCircle } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, newIdempotencyKey } from "../api/client";
import { useAssess, useAuthorize, useCancelPayment, useDashboard, useRecipients, useRefreshStatus } from "../api/hooks";
import type { Payment, Recipient, SimulatedOutcome } from "../api/types";
import Money from "../components/Money";
import RiskCard from "../components/RiskCard";
import { Button, Card, ErrorState, Field, LoadingState, PageHeader, SimTag, StateBadge, cx, inputClass } from "../components/ui";

type Step = "recipient" | "confirm" | "details" | "review" | "result";
const STEPS: { id: Step; label: string }[] = [
  { id: "recipient", label: "Recipient" }, { id: "confirm", label: "Confirm" }, { id: "details", label: "Amount" },
  { id: "review", label: "Risk review" }, { id: "result", label: "Result" },
];

const VERIFICATION_CHECKS = [
  "I know this recipient, or it's a business I chose myself.",
  "Nobody contacted me and asked me to make this payment urgently.",
  "I'm not paying to receive a refund, prize, loan, job or investment return.",
];

function Stepper({ step }: { step: Step }) {
  const current = STEPS.findIndex((s) => s.id === step);
  return (
    <ol className="mb-6 grid grid-cols-5 gap-2" aria-label="Payment steps">
      {STEPS.map((s, i) => (
        <li key={s.id} aria-current={i === current ? "step" : undefined}
          className={cx("border-t-4 pt-2 text-xs font-medium",
            i < current ? "border-teal-400 text-slate-600" : i === current ? "border-teal-700 text-slate-900 dark:text-white" : "border-slate-200 text-slate-400 dark:border-slate-700")}>
          <span className={cx(i !== current && "hidden sm:inline")}>{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

function RecipientIcon({ r }: { r: Pick<Recipient, "payment_type"> }) {
  const Icon = r.payment_type === "P2M" ? Store : User;
  return <span className="grid size-10 shrink-0 place-items-center rounded-full bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"><Icon className="size-5" aria-hidden /></span>;
}

const KIND_LABEL: Record<Recipient["kind"], string> = {
  yogii_user: "Yogii user (P2P)", merchant: "Merchant (P2M)", contact: "Demo contact (P2P)", unverified: "Unverified UPI ID",
};

export default function SendPage() {
  const [step, setStep] = useState<Step>("recipient");
  const [query, setQuery] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [looking, setLooking] = useState(false);
  const [recipient, setRecipient] = useState<Recipient | null>(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [device, setDevice] = useState("primary");
  const [location, setLocation] = useState("home");
  const [outcome, setOutcome] = useState<SimulatedOutcome>("SUCCESS");
  const [amountError, setAmountError] = useState("");
  const [payment, setPayment] = useState<Payment | null>(null);
  const [checks, setChecks] = useState<boolean[]>(VERIFICATION_CHECKS.map(() => false));
  const [flowError, setFlowError] = useState("");
  // One key per attempt: retries of the same submission can never create a second payment.
  const assessKey = useRef(newIdempotencyKey());
  const authorizeKey = useRef(newIdempotencyKey());
  const heading = useRef<HTMLHeadingElement>(null);

  const recipients = useRecipients();
  const dashboard = useDashboard();
  const assess = useAssess();
  const authorize = useAuthorize();
  const cancel = useCancelPayment();
  const refresh = useRefreshStatus();
  const navigate = useNavigate();

  useEffect(() => { heading.current?.focus(); }, [step]);

  const lookup = async (value: string) => {
    setLookupError("");
    if (value.trim().length < 3) { setLookupError("Enter a UPI ID (name@bank) or a 10-digit mobile number."); return; }
    setLooking(true);
    try {
      const r = await api<Recipient>(`/recipients/lookup?q=${encodeURIComponent(value.trim())}`);
      setRecipient(r);
      setStep("confirm");
    } catch (err) {
      setLookupError(err instanceof ApiError ? err.message : "Lookup failed. Try again.");
    } finally {
      setLooking(false);
    }
  };

  const submitDetails = (e: FormEvent) => {
    e.preventDefault();
    setAmountError("");
    const n = Number(amount);
    if (!/^\d+(\.\d{1,2})?$/.test(amount.trim()) || !(n > 0)) { setAmountError("Enter an amount in rupees, like 500 or 1250.50."); return; }
    if (n > 100000) { setAmountError("The simulation limit is ₹1,00,000 per payment."); return; }
    if (dashboard.data && n > Number(dashboard.data.simulated_balance)) { setAmountError("That's more than your simulated balance."); return; }
    assess.mutate({ recipient_upi: recipient!.upi_id, amount: n, note, device, location, key: assessKey.current }, {
      onSuccess: (p) => { setPayment(p); setStep("review"); },
      onError: (err) => setAmountError(err instanceof ApiError ? err.message : "The risk check failed. Try again."),
    });
  };

  const doAuthorize = () => {
    setFlowError("");
    authorize.mutate({
      payment_id: payment!.id, demo_verification_confirmed: payment!.actions.needs_verification && checks.every(Boolean),
      simulated_outcome: outcome, key: authorizeKey.current,
    }, {
      onSuccess: (p) => { setPayment(p); setStep("result"); },
      onError: (err) => setFlowError(err instanceof ApiError ? err.message : "Authorisation failed."),
    });
  };

  const doCancel = () => cancel.mutate(payment!.id, {
    onSuccess: (p) => { setPayment(p); setStep("result"); },
    onError: (err) => setFlowError(err instanceof ApiError ? err.message : "Couldn't cancel."),
  });

  const checkStatus = () => refresh.mutate(payment!.id, {
    onSuccess: async () => setPayment(await api<Payment>(`/payments/${payment!.id}`)),
  });

  const restart = () => {
    setStep("recipient"); setRecipient(null); setQuery(""); setAmount(""); setNote(""); setPayment(null);
    setChecks(VERIFICATION_CHECKS.map(() => false)); setDevice("primary"); setLocation("home"); setOutcome("SUCCESS");
    assessKey.current = newIdempotencyKey(); authorizeKey.current = newIdempotencyKey();
  };

  const title = { recipient: "Send money", confirm: "Confirm recipient", details: "Enter amount", review: "Review the risk check", result: "Payment result" }[step];

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={title} subtitle="Simulated payment: no real money moves." />
      <h2 ref={heading} tabIndex={-1} className="sr-only">{title}</h2>
      <Stepper step={step} />

      {step === "recipient" && (
        <div className="flex flex-col gap-4">
          <Card>
            <form onSubmit={(e) => { e.preventDefault(); lookup(query); }} className="flex flex-col gap-3" noValidate>
              <Field id="recipient-query" label="UPI ID or mobile number" hint="For example rahul@upi or 9876543211" error={lookupError}>
                <input id="recipient-query" className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)}
                  autoComplete="off" aria-invalid={Boolean(lookupError) || undefined}
                  aria-describedby={lookupError ? "recipient-query-error" : "recipient-query-hint"} />
              </Field>
              <Button type="submit" loading={looking}><Search className="size-4" aria-hidden />Find recipient</Button>
            </form>
          </Card>
          <Card aria-labelledby="saved-title">
            <h3 id="saved-title" className="mb-2 font-semibold">Demo payees</h3>
            {recipients.isPending && <LoadingState label="Loading payees…" />}
            {recipients.isError && <ErrorState message={recipients.error.message} onRetry={() => recipients.refetch()} />}
            {recipients.data && (
              <ul className="grid gap-1 sm:grid-cols-2">
                {recipients.data.map((r) => (
                  <li key={r.upi_id}>
                    <button type="button" onClick={() => { setRecipient(r); setStep("confirm"); }}
                      className="flex w-full items-center gap-3 rounded-xl p-2 text-left hover:bg-slate-50 focus-visible:outline-3 focus-visible:outline-teal-600 dark:hover:bg-slate-800">
                      <RecipientIcon r={r} />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{r.name}</span>
                        <span className="block truncate font-mono text-xs text-slate-500">{r.upi_id}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      {step === "confirm" && recipient && (
        <Card className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <RecipientIcon r={recipient} />
            <div>
              <p className="text-lg font-semibold">{recipient.name}</p>
              <p className="font-mono text-sm text-slate-600 dark:text-slate-400">{recipient.upi_id}</p>
              <p className="text-sm text-slate-600 dark:text-slate-400">{KIND_LABEL[recipient.kind]}
                {recipient.merchant_category ? ` · ${recipient.merchant_category}` : ""}</p>
            </div>
          </div>
          {recipient.kind === "unverified" ? (
            <p role="note" className="flex gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              <ShieldAlert className="size-5 shrink-0" aria-hidden />{recipient.notice}
            </p>
          ) : (
            <p className="flex gap-2 text-sm text-slate-600 dark:text-slate-400"><BadgeCheck className="size-5 text-teal-700" aria-hidden />
              Name from the Yogii demo directory (fictional).</p>
          )}
          <p className="text-sm text-slate-600 dark:text-slate-400">Check this is the person or business you mean to pay. The risk check comes next.</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setStep("details")}>Yes, pay this recipient</Button>
            <Button variant="secondary" onClick={() => setStep("recipient")}><ArrowLeft className="size-4" aria-hidden />Choose someone else</Button>
          </div>
        </Card>
      )}

      {step === "details" && recipient && (
        <Card>
          <form onSubmit={submitDetails} className="flex flex-col gap-4" noValidate>
            <p className="text-sm text-slate-600 dark:text-slate-400">Paying <strong>{recipient.name}</strong> <span className="font-mono">{recipient.upi_id}</span></p>
            <Field id="amount" label="Amount (₹)" error={amountError}
              hint={dashboard.data ? `Simulated balance: ₹${Number(dashboard.data.simulated_balance).toLocaleString("en-IN")}` : undefined}>
              <input id="amount" inputMode="decimal" className={cx(inputClass, "text-2xl font-semibold")} value={amount}
                onChange={(e) => setAmount(e.target.value)} aria-invalid={Boolean(amountError) || undefined}
                aria-describedby={amountError ? "amount-error" : "amount-hint"} autoComplete="off" />
            </Field>
            <Field id="note" label="Note (optional)">
              <input id="note" maxLength={80} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <fieldset className="flex flex-col gap-3 rounded-xl border border-dashed border-amber-400 p-4">
              <legend className="px-1 text-sm font-semibold">Simulation controls <SimTag className="ml-1" /></legend>
              <p className="text-xs text-slate-600 dark:text-slate-400">Demo-only inputs that let you try the risk signals and the mock bank's outcomes.</p>
              <Field id="device" label="Simulated device">
                <select id="device" className={inputClass} value={device} onChange={(e) => setDevice(e.target.value)}>
                  <option value="primary">My usual phone</option>
                  <option value="new-phone">A new phone</option>
                </select>
              </Field>
              <Field id="location" label="Simulated location">
                <select id="location" className={inputClass} value={location} onChange={(e) => setLocation(e.target.value)}>
                  <option value="home">My usual city</option>
                  <option value="unfamiliar-city">An unfamiliar city</option>
                </select>
              </Field>
              <Field id="outcome" label="Mock bank outcome">
                <select id="outcome" className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value as SimulatedOutcome)}>
                  <option value="SUCCESS">Success</option>
                  <option value="FAILURE">Failure</option>
                  <option value="PENDING">Pending</option>
                </select>
              </Field>
            </fieldset>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={assess.isPending}>Check risk</Button>
              <Button type="button" variant="secondary" onClick={() => setStep("confirm")}><ArrowLeft className="size-4" aria-hidden />Back</Button>
            </div>
            {assess.isPending && <p role="status" className="text-sm text-slate-600">Checking this payment for fraud-risk signals…</p>}
          </form>
        </Card>
      )}

      {step === "review" && payment?.risk && (
        <div className="flex flex-col gap-4">
          <Card className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-500">You're paying</p>
              <p className="font-semibold">{payment.recipient.name}</p>
            </div>
            <Money amount={payment.amount} className="text-2xl font-bold tabular-nums" />
          </Card>
          <RiskCard risk={payment.risk} />
          {payment.risk.blocked ? (
            <Card className="flex flex-col gap-3">
              <p className="text-sm">This attempt has been recorded. No money moved, and it can't be authorised.
                If you think this is a mistake, don't try again with a different amount; check the recipient first.</p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => setStep("result")}>See result</Button>
              </div>
            </Card>
          ) : (
            <Card className="flex flex-col gap-4" aria-labelledby="authorise-title">
              <h2 id="authorise-title" className="font-semibold">Authorise the simulated payment</h2>
              {payment.actions.needs_verification && (
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-1 text-sm font-semibold">Demo verification: confirm all of these</legend>
                  {VERIFICATION_CHECKS.map((text, i) => (
                    <label key={text} className="flex items-start gap-3 text-sm">
                      <input type="checkbox" className="mt-0.5 size-5 accent-teal-700" checked={checks[i]}
                        onChange={(e) => setChecks(checks.map((c, j) => (j === i ? e.target.checked : c)))} />
                      {text}
                    </label>
                  ))}
                </fieldset>
              )}
              <p className="text-xs text-slate-600 dark:text-slate-400">
                Yogii never asks for your UPI PIN, OTP or bank password. With a future real bank integration, your bank's
                own secure screen would handle that step.
              </p>
              {flowError && <p role="alert" className="text-sm font-medium text-red-700">{flowError}</p>}
              <div className="flex flex-wrap gap-2">
                <Button onClick={doAuthorize} loading={authorize.isPending}
                  disabled={payment.actions.needs_verification && !checks.every(Boolean)}>
                  Authorise simulated payment
                </Button>
                <Button variant="secondary" onClick={doCancel} loading={cancel.isPending}>Cancel payment</Button>
              </div>
            </Card>
          )}
        </div>
      )}

      {step === "result" && payment && <Result payment={payment} onCheck={checkStatus} checking={refresh.isPending}
        onNew={restart} onHome={() => navigate("/")} />}
    </div>
  );
}

function Result({ payment, onCheck, checking, onNew, onHome }: {
  payment: Payment; onCheck: () => void; checking: boolean; onNew: () => void; onHome: () => void;
}) {
  const view = {
    COMPLETED: { icon: CheckCircle2, color: "text-emerald-600", title: "Payment completed", body: "The simulated money has moved." },
    PENDING: { icon: Clock, color: "text-sky-600", title: "Payment pending", body: "The mock bank hasn't confirmed it yet. Your balance changes only when it completes." },
    BLOCKED: { icon: ShieldAlert, color: "text-red-700", title: "Payment blocked", body: "The risk check stopped this payment before authorisation. No money moved." },
    FAILED: { icon: XCircle, color: "text-red-700", title: "Payment not completed", body: `${payment.failure_reason ?? ""} Your balance did not change.` },
  }[payment.state as "COMPLETED" | "PENDING" | "BLOCKED" | "FAILED"] ?? {
    icon: Clock, color: "text-slate-500", title: "Payment in progress", body: "",
  };
  const Icon = view.icon;
  return (
    <Card className="flex flex-col items-center gap-3 py-8 text-center" aria-live="polite">
      <Icon className={cx("size-12", view.color)} aria-hidden />
      <h2 className="text-xl font-bold">{view.title}</h2>
      <Money amount={payment.amount} className="text-3xl font-bold tabular-nums" />
      <p>to {payment.recipient.name} <span className="font-mono text-sm text-slate-500">{payment.recipient.upi_id}</span></p>
      <div className="flex items-center gap-2"><StateBadge state={payment.state} /><SimTag /></div>
      <p className="max-w-md text-sm text-slate-600 dark:text-slate-400">{view.body}</p>
      <p className="font-mono text-xs text-slate-500">Reference {payment.reference}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        {payment.state === "PENDING" && <Button onClick={onCheck} loading={checking}>Check status</Button>}
        <Link to={`/payments/${payment.id}`} className="inline-flex min-h-11 items-center rounded-xl border border-slate-300 px-4 text-sm font-semibold dark:border-slate-700">View details</Link>
        <Button variant="secondary" onClick={onNew}>New payment</Button>
        <Button variant="ghost" onClick={onHome}>Back to home</Button>
      </div>
    </Card>
  );
}
