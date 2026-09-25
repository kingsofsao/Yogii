import React from "react";
import { Send, ShieldCheck, ShieldAlert, ArrowUpRight, Clock, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

export default function DashboardView({ dashboardData, onNavigateToSend, onSelectTransaction }) {
  if (!dashboardData) {
    return (
      <div style={{ textAlign: "center", padding: "60px 20px" }}>
        <div style={{ color: "var(--text-muted)" }}>Loading simulated dashboard data...</div>
      </div>
    );
  }

  const { user, simulated_balance, stats, recent_payments, recipients } = dashboardData;

  function renderStatusBadge(state) {
    switch (state) {
      case "COMPLETED":
        return <span className="badge badge-completed"><CheckCircle2 size={12} /> Completed</span>;
      case "BLOCKED":
        return <span className="badge badge-blocked"><XCircle size={12} /> Blocked</span>;
      case "NEEDS_VERIFICATION":
        return <span className="badge badge-medium"><AlertTriangle size={12} /> Needs Verification</span>;
      case "PENDING":
        return <span className="badge badge-pending"><Clock size={12} /> Pending</span>;
      case "FAILED":
        return <span className="badge badge-blocked"><XCircle size={12} /> Failed</span>;
      default:
        return <span className="badge">{state}</span>;
    }
  }

  function renderRiskBadge(riskAssessment) {
    if (!riskAssessment) return null;
    const { risk_band, raw_risk_score } = riskAssessment;
    const bandCls = risk_band === "LOW" ? "badge-low" :
                    risk_band === "MEDIUM" ? "badge-medium" :
                    risk_band === "HIGH" ? "badge-high" : "badge-very-high";
    return (
      <span className={`badge ${bandCls}`} title={`Score: ${raw_risk_score}`}>
        {risk_band} ({raw_risk_score})
      </span>
    );
  }

  return (
    <div>
      {/* Balance Card */}
      <div className="card balance-card">
        <div className="balance-title">
          <span>Simulated Account Balance</span>
          <span className="sim-pill" style={{ background: "rgba(255,255,255,0.2)" }}>Mock Balance</span>
        </div>
        <div className="balance-amount">
          ₹{simulated_balance.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        <div className="balance-meta">
          <div>UPI ID: <strong>{user?.upi_id}</strong></div>
          <div>Status: <strong>Active (Simulated)</strong></div>
          <div>Currency: <strong>INR</strong></div>
        </div>

        <div style={{ marginTop: "24px" }}>
          <button className="btn btn-primary" onClick={onNavigateToSend} style={{ background: "#3b82f6" }}>
            <Send size={16} /> Send Simulated Payment
          </button>
        </div>
      </div>

      {/* Risk Metrics Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px", marginBottom: "24px" }}>
        <div className="card" style={{ padding: "18px", margin: 0 }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 600 }}>Total Payments</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, marginTop: "6px" }}>{stats?.total_transactions || 0}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "4px" }}>Simulated test executions</div>
        </div>

        <div className="card" style={{ padding: "18px", margin: 0 }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 600 }}>Completed</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--success)", marginTop: "6px" }}>{stats?.completed || 0}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "4px" }}>Balances debited exactly once</div>
        </div>

        <div className="card" style={{ padding: "18px", margin: 0 }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 600 }}>Blocked by Risk</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--danger)", marginTop: "6px" }}>{stats?.blocked_by_risk_policy || 0}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "4px" }}>Threshold score &ge; 85</div>
        </div>

        <div className="card" style={{ padding: "18px", margin: 0 }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 600 }}>Verified Reviews</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--warning)", marginTop: "6px" }}>{stats?.verified_reviews || 0}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "4px" }}>Medium/High demo verified</div>
        </div>
      </div>

      {/* Quick Pay Contacts */}
      {recipients && recipients.length > 0 && (
        <div className="card" style={{ padding: "20px" }}>
          <div style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: "12px", display: "flex", justifyContent: "space-between" }}>
            <span>Demo Recipients & Contacts</span>
            <span style={{ fontSize: "0.8rem", fontWeight: 400, color: "var(--text-muted)" }}>Fictional Profiles</span>
          </div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            {recipients.map((rec) => (
              <button
                key={rec.id}
                className="btn btn-secondary"
                style={{ fontSize: "0.85rem", padding: "8px 12px" }}
                onClick={() => onNavigateToSend(rec.upi_id)}
              >
                <strong>{rec.name}</strong> ({rec.upi_id})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Recent Payments Table */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ fontSize: "1.05rem", fontWeight: 700 }}>Recent Simulated Transactions</h2>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Click any row to view full risk audit and feature snapshot</div>
          </div>
        </div>

        <div className="table-responsive">
          <table>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Recipient</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Risk Band</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {recent_payments && recent_payments.length > 0 ? (
                recent_payments.map((tx) => (
                  <tr
                    key={tx.id}
                    onClick={() => onSelectTransaction(tx)}
                    style={{ cursor: "pointer" }}
                    title="Click for transaction risk detail"
                  >
                    <td style={{ fontFamily: "monospace", fontSize: "0.85rem", color: "var(--primary)" }}>
                      {tx.reference}
                    </td>
                    <td><strong>{tx.recipient_upi}</strong></td>
                    <td style={{ fontWeight: 600 }}>
                      ₹{tx.amount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td>{renderStatusBadge(tx.state)}</td>
                    <td>{renderRiskBadge(tx.risk_assessment)}</td>
                    <td style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
                      {new Date(tx.created_at).toLocaleDateString()} {new Date(tx.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "40px 20px", color: "var(--text-muted)" }}>
                    No transactions yet. Click 'Send Simulated Payment' above to execute a mock transfer.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
