import React from "react";
import { X, ShieldAlert, CheckCircle2, XCircle, AlertTriangle, Clock, Hash, Shield } from "lucide-react";

export default function TransactionDetailModal({ transaction, onClose }) {
  if (!transaction) return null;

  const ra = transaction.risk_assessment;

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: "600px" }}>
        <div className="modal-header">
          <div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
              Transaction Risk Audit
            </div>
            <div style={{ fontFamily: "monospace", fontSize: "1.1rem", fontWeight: 700, color: "var(--primary)" }}>
              {transaction.reference}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {/* Status & Amount Highlight */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px", background: "var(--bg-muted)", borderRadius: "8px", marginBottom: "18px" }}>
            <div>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Transaction Amount</div>
              <div style={{ fontSize: "1.8rem", fontWeight: 800 }}>
                ₹{transaction.amount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "4px" }}>Execution State</div>
              <span className={`badge ${
                transaction.state === "COMPLETED" ? "badge-completed" :
                transaction.state === "BLOCKED" ? "badge-blocked" :
                transaction.state === "NEEDS_VERIFICATION" ? "badge-medium" : "badge-pending"
              }`}>
                {transaction.state}
              </span>
            </div>
          </div>

          {/* Model Risk Assessment */}
          {ra ? (
            <div style={{ border: "1px solid var(--border)", borderRadius: "8px", padding: "16px", marginBottom: "18px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div style={{ fontWeight: 700, fontSize: "0.92rem", display: "flex", alignItems: "center", gap: "6px" }}>
                  <Shield size={17} color="var(--primary)" />
                  <span>XGBoost Fraud Assessment</span>
                </div>
                <span className={`badge ${
                  ra.risk_band === "LOW" ? "badge-low" :
                  ra.risk_band === "MEDIUM" ? "badge-medium" :
                  ra.risk_band === "HIGH" ? "badge-high" : "badge-very-high"
                }`}>
                  {ra.risk_band} RISK (Score: {ra.raw_risk_score})
                </span>
              </div>

              <div style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: "12px" }}>
                Model Version: <strong>{ra.model_version}</strong> &bull; Decision: <strong>{ra.decision}</strong>
              </div>

              <div>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-main)", marginBottom: "6px" }}>
                  Triggered Indicators:
                </div>
                <div className="risk-reasons-list">
                  {ra.reason_codes && ra.reason_codes.length > 0 ? (
                    ra.reason_codes.map((rc, idx) => (
                      <div key={idx} className="risk-reason-card" style={{ padding: "8px 12px" }}>
                        <AlertTriangle size={15} color="#d97706" style={{ flexShrink: 0, marginTop: "2px" }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.78rem", color: "var(--text-muted)" }}>{rc.code}</div>
                          <div style={{ fontSize: "0.84rem" }}>{rc.description}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ fontSize: "0.84rem", color: "var(--text-muted)" }}>No elevated risk indicators detected.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ padding: "12px", background: "var(--bg-muted)", borderRadius: "8px", fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "18px" }}>
              No risk assessment record associated with this payment attempt.
            </div>
          )}

          {/* Technical Metadata & Invariants */}
          <div style={{ fontSize: "0.82rem", color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: "8px" }}>
            <div>Recipient UPI: <strong style={{ color: "var(--text-main)" }}>{transaction.recipient_upi}</strong></div>
            <div>Idempotency Key: <code style={{ fontSize: "0.78rem" }}>{transaction.idempotency_key}</code></div>
            <div>Payment Rail: <strong style={{ color: "var(--text-main)" }}>{transaction.provider}</strong></div>
            <div>Created At: <strong style={{ color: "var(--text-main)" }}>{new Date(transaction.created_at).toLocaleString()}</strong></div>
            {transaction.failure_reason && (
              <div style={{ color: "var(--danger)" }}>Failure / Block Reason: {transaction.failure_reason}</div>
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
