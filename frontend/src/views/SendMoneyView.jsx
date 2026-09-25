import React, { useState } from "react";
import {
  Send, ShieldCheck, ShieldAlert, AlertTriangle, CheckCircle2,
  XCircle, ArrowRight, Loader2, RefreshCw, Lock, ExternalLink
} from "lucide-react";
import { apiRequest } from "../api/client";

export default function SendMoneyView({ initialRecipient, balance, onPaymentCompleted }) {
  // Steps: 'input' -> 'assessing' -> 'review' -> 'verifying' -> 'result'
  const [step, setStep] = useState("input");
  const [recipientUpi, setRecipientUpi] = useState(initialRecipient || "rahul@upi");
  const [amount, setAmount] = useState("");
  const [paymentType, setPaymentType] = useState("P2P");
  const [deviceId, setDeviceId] = useState("demo-device-default");
  const [location, setLocation] = useState("Chennai");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [assessmentResult, setAssessmentResult] = useState(null);
  const [verifiedResult, setVerifiedResult] = useState(null);

  // Demo verification state
  const [demoVerificationConfirmed, setDemoVerificationConfirmed] = useState(false);

  // Presets for quick testing
  function setTestScenario(type) {
    if (type === "routine") {
      setRecipientUpi("rahul@upi");
      setAmount("450");
      setDeviceId("demo-device-default");
      setLocation("Chennai");
    } else if (type === "medium_new") {
      setRecipientUpi("campuscafe@merchant");
      setAmount("3800");
      setDeviceId("demo-device-default");
      setLocation("Chennai");
    } else if (type === "high_velocity") {
      setRecipientUpi("newmerchant@upi");
      setAmount("12000");
      setDeviceId("demo-device-default");
      setLocation("Chennai");
    } else if (type === "blocked_crypto") {
      setRecipientUpi("crypto_drain@unknown");
      setAmount("24000");
      setDeviceId("untrusted-vpn-node");
      setLocation("Offshore");
    }
  }

  async function handleStartAssessment(e) {
    if (e) e.preventDefault();
    setError("");

    const parsedAmount = parseFloat(amount);
    if (isNaN(parsedAmount) || parsedAmount <= 0) {
      setError("Please enter a valid positive payment amount.");
      return;
    }

    if (parsedAmount > balance) {
      setError(`Requested amount (₹${parsedAmount.toLocaleString("en-IN")}) exceeds your simulated balance (₹${balance.toLocaleString("en-IN")}).`);
      return;
    }

    setStep("assessing");
    setLoading(true);

    try {
      // Create a deterministic idempotency key for this payment intent
      const idempotencyKey = `YOGII-IDEM-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`;
      const data = await apiRequest("/payments/assess", {
        method: "POST",
        body: JSON.stringify({
          recipient_upi: recipientUpi.trim(),
          amount: parsedAmount,
          idempotency_key: idempotencyKey,
          payment_type: paymentType,
          device_id: deviceId,
          location: location
        })
      });

      setAssessmentResult(data);

      if (data.state === "COMPLETED") {
        setVerifiedResult(data);
        setStep("result");
        onPaymentCompleted();
      } else if (data.state === "BLOCKED") {
        setStep("review");
      } else if (data.state === "NEEDS_VERIFICATION") {
        setStep("review");
      } else {
        setStep("review");
      }
    } catch (err) {
      setError(err.message || "Fraud assessment failed.");
      setStep("input");
    } finally {
      setLoading(false);
    }
  }

  async function handleDemoVerify(e) {
    if (e) e.preventDefault();
    if (!demoVerificationConfirmed) {
      setError("Please check the confirmation box to confirm this simulated demo transfer.");
      return;
    }

    setError("");
    setLoading(true);

    try {
      const data = await apiRequest(`/payments/${assessmentResult.id}/verify`, {
        method: "POST",
        body: JSON.stringify({
          demo_verification_confirmed: true
        })
      });

      setVerifiedResult(data);
      setStep("result");
      onPaymentCompleted();
    } catch (err) {
      setError(err.message || "Demo verification failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setStep("input");
    setAmount("");
    setAssessmentResult(null);
    setVerifiedResult(null);
    setDemoVerificationConfirmed(false);
    setError("");
  }

  return (
    <div style={{ maxWidth: "680px", margin: "0 auto" }}>
      {/* Simulation Pill Header */}
      <div style={{ marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ fontSize: "1.35rem", fontWeight: 700 }}>Simulated Payment Engine</h1>
        <span className="sim-pill">Simulation Rail</span>
      </div>

      {error && (
        <div style={{ padding: "12px 16px", background: "var(--danger-bg)", color: "#b91c1c", borderRadius: "8px", fontSize: "0.88rem", marginBottom: "18px", border: "1px solid #fecaca" }}>
          <strong>Error: </strong> {error}
        </div>
      )}

      {/* STEP 1: INPUT DETAILS */}
      {step === "input" && (
        <div className="card">
          {/* Quick Scenario Buttons */}
          <div style={{ padding: "12px", background: "var(--bg-muted)", borderRadius: "8px", marginBottom: "20px" }}>
            <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px" }}>
              Test Risk Scenarios:
            </div>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              <button type="button" className="btn btn-secondary" style={{ padding: "5px 10px", fontSize: "0.8rem" }} onClick={() => setTestScenario("routine")}>
                Routine (₹450 &bull; Low Risk)
              </button>
              <button type="button" className="btn btn-secondary" style={{ padding: "5px 10px", fontSize: "0.8rem" }} onClick={() => setTestScenario("medium_new")}>
                Medium Risk (₹3,800)
              </button>
              <button type="button" className="btn btn-secondary" style={{ padding: "5px 10px", fontSize: "0.8rem" }} onClick={() => setTestScenario("high_velocity")}>
                High Velocity (₹12,000)
              </button>
              <button type="button" className="btn btn-secondary" style={{ padding: "5px 10px", fontSize: "0.8rem", color: "#b91c1c" }} onClick={() => setTestScenario("blocked_crypto")}>
                Blocked (₹24,000 &bull; Risk &ge; 85)
              </button>
            </div>
          </div>

          <form onSubmit={handleStartAssessment}>
            <div className="form-group">
              <label className="form-label">Recipient UPI ID or Phone</label>
              <input
                type="text"
                className="form-input"
                required
                value={recipientUpi}
                onChange={(e) => setRecipientUpi(e.target.value)}
                placeholder="e.g. rahul@upi or merchant@upi"
              />
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "4px" }}>
                Supports demo UPI handles, phone numbers, and fictional merchants.
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Payment Amount (INR)</label>
              <input
                type="number"
                step="any"
                min="1"
                max="100000"
                className="form-input"
                required
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="₹ Amount to send"
                style={{ fontSize: "1.2rem", fontWeight: 700 }}
              />
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "4px", display: "flex", justifyContent: "space-between" }}>
                <span>Available Simulated Balance:</span>
                <strong>₹{balance.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "18px" }}>
              <div>
                <label className="form-label" style={{ fontSize: "0.8rem" }}>Payment Type</label>
                <select
                  className="form-input"
                  value={paymentType}
                  onChange={(e) => setPaymentType(e.target.value)}
                  style={{ fontSize: "0.85rem" }}
                >
                  <option value="P2P">Peer-to-Peer (P2P)</option>
                  <option value="P2M">Peer-to-Merchant (P2M)</option>
                </select>
              </div>

              <div>
                <label className="form-label" style={{ fontSize: "0.8rem" }}>Simulated Location</label>
                <input
                  type="text"
                  className="form-input"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  style={{ fontSize: "0.85rem" }}
                />
              </div>
            </div>

            <div style={{ padding: "12px", background: "#f8fafc", border: "1px solid var(--border)", borderRadius: "8px", fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: "20px" }}>
              🛡️ <strong>Safety Invariant:</strong> Yogii NEVER requests your UPI PIN, banking password, or OTP. The payment risk engine evaluates features before execution.
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: "100%", padding: "12px", fontSize: "1rem" }} disabled={loading}>
              Assess Fraud Risk &amp; Continue <ArrowRight size={18} />
            </button>
          </form>
        </div>
      )}

      {/* STEP 2: REAL-TIME ASSESSMENT LOADING */}
      {step === "assessing" && (
        <div className="card" style={{ textAlign: "center", padding: "50px 20px" }}>
          <Loader2 size={44} className="spin" color="var(--primary)" style={{ animation: "spin 1s linear infinite", margin: "0 auto 16px" }} />
          <h2 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "8px" }}>Evaluating Transaction Risk</h2>
          <div style={{ color: "var(--text-muted)", fontSize: "0.88rem", maxWidth: "420px", margin: "0 auto" }}>
            Extracting 23 behavioural and network graph features. Running XGBoost classifier inference...
          </div>
          <style>{`@keyframes spin { 100% { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* STEP 3: RISK REVIEW SCREEN */}
      {step === "review" && assessmentResult && (
        <div className="card">
          <div style={{ textAlign: "center", marginBottom: "20px" }}>
            <div style={{ fontSize: "0.8rem", textTransform: "uppercase", fontWeight: 700, color: "var(--text-muted)" }}>
              Yogii Fraud Intelligence Result
            </div>

            {/* Risk Score Meter Box */}
            <div className="risk-meter-box" style={{
              background: assessmentResult.risk_assessment?.risk_band === "VERY_HIGH" ? "var(--danger-bg)" :
                          assessmentResult.risk_assessment?.risk_band === "HIGH" ? "#fff7ed" :
                          assessmentResult.risk_assessment?.risk_band === "MEDIUM" ? "var(--warning-bg)" : "var(--success-bg)",
              borderColor: assessmentResult.risk_assessment?.risk_band === "VERY_HIGH" ? "#fecaca" :
                           assessmentResult.risk_assessment?.risk_band === "HIGH" ? "#fed7aa" :
                           assessmentResult.risk_assessment?.risk_band === "MEDIUM" ? "#fde68a" : "#a7f3d0"
            }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>Risk Score</div>
              <div className="risk-score-display" style={{
                color: assessmentResult.risk_assessment?.risk_band === "VERY_HIGH" ? "var(--danger)" :
                       assessmentResult.risk_assessment?.risk_band === "HIGH" ? "#c2410c" :
                       assessmentResult.risk_assessment?.risk_band === "MEDIUM" ? "var(--warning)" : "var(--success)"
              }}>
                {assessmentResult.risk_assessment?.raw_risk_score}
              </div>
              <div style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", fontSize: "0.95rem" }}>
                {assessmentResult.risk_assessment?.risk_band} RISK
              </div>
            </div>
          </div>

          {/* Transaction Summary */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", padding: "14px", background: "var(--bg-muted)", borderRadius: "8px", fontSize: "0.85rem", marginBottom: "18px" }}>
            <div>Recipient: <strong>{assessmentResult.recipient_upi}</strong></div>
            <div>Amount: <strong>₹{assessmentResult.amount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong></div>
            <div>Reference: <span style={{ fontFamily: "monospace" }}>{assessmentResult.reference}</span></div>
            <div>Rail: <strong>MockPaymentProvider (Simulated)</strong></div>
          </div>

          {/* Understandable Reason Codes */}
          <div style={{ marginBottom: "20px" }}>
            <div style={{ fontSize: "0.85rem", fontWeight: 700, marginBottom: "8px" }}>
              Risk Assessment Findings:
            </div>
            <div className="risk-reasons-list">
              {assessmentResult.risk_assessment?.reason_codes?.map((r, idx) => (
                <div key={idx} className="risk-reason-card">
                  <AlertTriangle size={18} color={assessmentResult.risk_assessment?.risk_band === "VERY_HIGH" ? "var(--danger)" : "var(--warning)"} style={{ flexShrink: 0, marginTop: "2px" }} />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.82rem", color: "var(--text-muted)" }}>{r.code}</div>
                    <div>{r.description}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Action branching based on Risk Band */}
          {assessmentResult.state === "BLOCKED" ? (
            <div>
              <div style={{ padding: "14px", background: "var(--danger-bg)", color: "#991b1b", borderRadius: "8px", fontSize: "0.88rem", marginBottom: "18px" }}>
                <strong>🚫 Payment Blocked:</strong> {assessmentResult.failure_reason || "The simulated payment was blocked because the risk assessment crossed the Yogii prototype threshold (Score >= 85)."}
                <div style={{ marginTop: "6px", fontSize: "0.8rem", color: "#7f1d1d" }}>
                  Invariant: No funds have been debited from your simulated balance.
                </div>
              </div>

              <button className="btn btn-secondary" style={{ width: "100%" }} onClick={handleReset}>
                Return to Dashboard
              </button>
            </div>
          ) : (
            <div>
              {/* Needs verification warning */}
              <div style={{ padding: "14px", background: "var(--warning-bg)", color: "#92400e", borderRadius: "8px", fontSize: "0.88rem", marginBottom: "18px" }}>
                <strong>⚠️ Verification Required:</strong> This payment scored in the {assessmentResult.risk_assessment?.risk_band} band. To proceed with the simulated clearing rail, complete the Demo Verification challenge below.
              </div>

              {/* DEMO VERIFICATION STEP (NEVER asks for PIN or OTP) */}
              <div style={{ border: "2px dashed #f59e0b", borderRadius: "8px", padding: "16px", background: "#fff", marginBottom: "18px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, color: "#92400e", marginBottom: "8px" }}>
                  <ShieldCheck size={20} />
                  <span>DEMO VERIFICATION (SIMULATED CHALLENGE)</span>
                </div>
                <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "12px" }}>
                  This is a prototype in-app secondary challenge. Yogii will <strong>NEVER</strong> ask for your UPI PIN, ATM PIN, or OTP.
                </p>

                <label style={{ display: "flex", alignItems: "flex-start", gap: "10px", fontSize: "0.88rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={demoVerificationConfirmed}
                    onChange={(e) => setDemoVerificationConfirmed(e.target.checked)}
                    style={{ marginTop: "4px", width: "18px", height: "18px" }}
                  />
                  <span>
                    I confirm that I understand this payment scored {assessmentResult.risk_assessment?.raw_risk_score} ({assessmentResult.risk_assessment?.risk_band} Risk) and wish to authorize this <strong>SIMULATED</strong> mock transfer.
                  </span>
                </label>
              </div>

              <div style={{ display: "flex", gap: "12px" }}>
                <button className="btn btn-secondary" style={{ flex: 1 }} onClick={handleReset}>
                  Cancel Payment
                </button>
                <button
                  className="btn btn-primary"
                  style={{ flex: 2 }}
                  onClick={handleDemoVerify}
                  disabled={loading || !demoVerificationConfirmed}
                >
                  {loading ? "Verifying..." : "Authorize Demo Payment"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* STEP 4: PAYMENT RESULT SCREEN */}
      {step === "result" && verifiedResult && (
        <div className="card" style={{ textAlign: "center", padding: "36px 24px" }}>
          {verifiedResult.state === "COMPLETED" ? (
            <div>
              <div style={{ width: "64px", height: "64px", background: "var(--success-bg)", color: "var(--success)", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
                <CheckCircle2 size={36} />
              </div>
              <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "#065f46", marginBottom: "4px" }}>
                Simulated Payment Completed
              </h2>
              <p style={{ color: "var(--text-muted)", fontSize: "0.88rem", marginBottom: "20px" }}>
                Mock clearing switch executed successfully. Simulated balance debited exactly once.
              </p>

              <div style={{ background: "var(--bg-muted)", borderRadius: "8px", padding: "18px", textAlign: "left", maxWidth: "440px", margin: "0 auto 24px", fontSize: "0.88rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ color: "var(--text-muted)" }}>Amount:</span>
                  <strong>₹{verifiedResult.amount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ color: "var(--text-muted)" }}>Recipient:</span>
                  <strong>{verifiedResult.recipient_upi}</strong>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ color: "var(--text-muted)" }}>Payment Reference:</span>
                  <span style={{ fontFamily: "monospace", color: "var(--primary)" }}>{verifiedResult.reference}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-muted)" }}>Rail Provider:</span>
                  <span>{verifiedResult.provider}</span>
                </div>
              </div>
            </div>
          ) : (
            <div>
              <div style={{ width: "64px", height: "64px", background: "var(--danger-bg)", color: "var(--danger)", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
                <XCircle size={36} />
              </div>
              <h2 style={{ fontSize: "1.4rem", fontWeight: 700, color: "#991b1b", marginBottom: "4px" }}>
                Simulated Payment {verifiedResult.state}
              </h2>
              <p style={{ color: "var(--text-muted)", fontSize: "0.88rem", marginBottom: "20px" }}>
                {verifiedResult.failure_reason || "The transaction could not be completed on the simulated rail."}
              </p>
            </div>
          )}

          <button className="btn btn-primary" onClick={handleReset}>
            Make Another Payment
          </button>
        </div>
      )}
    </div>
  );
}
