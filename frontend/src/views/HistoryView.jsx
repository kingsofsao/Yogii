import React, { useState, useEffect } from "react";
import { Search, Filter, CheckCircle2, XCircle, AlertTriangle, Clock } from "lucide-react";
import { apiRequest } from "../api/client";

export default function HistoryView({ onSelectTransaction }) {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    fetchHistory();
  }, [filterState]);

  async function fetchHistory() {
    setLoading(true);
    try {
      const path = filterState ? `/payments?status_filter=${filterState}` : "/payments";
      const data = await apiRequest(path);
      setPayments(data || []);
    } catch (err) {
      console.error("Failed to load payment history:", err);
    } finally {
      setLoading(false);
    }
  }

  const filteredPayments = payments.filter((p) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      p.reference.toLowerCase().includes(q) ||
      p.recipient_upi.toLowerCase().includes(q) ||
      p.amount.toString().includes(q)
    );
  });

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
    if (!riskAssessment) return <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>N/A</span>;
    const { risk_band, raw_risk_score } = riskAssessment;
    const bandCls = risk_band === "LOW" ? "badge-low" :
                    risk_band === "MEDIUM" ? "badge-medium" :
                    risk_band === "HIGH" ? "badge-high" : "badge-very-high";
    return (
      <span className={`badge ${bandCls}`}>
        {risk_band} ({raw_risk_score})
      </span>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h1 style={{ fontSize: "1.35rem", fontWeight: 700 }}>Payment History &amp; Audit Logs</h1>
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            Complete audit trail of all evaluated, completed, and blocked simulated payments.
          </p>
        </div>
        <span className="sim-pill">Simulated Ledger</span>
      </div>

      <div className="card" style={{ padding: "16px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "center", marginBottom: "16px" }}>
        <div style={{ flex: 1, minWidth: "220px", position: "relative" }}>
          <input
            type="text"
            className="form-input"
            placeholder="Search by reference or recipient..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          {["", "COMPLETED", "NEEDS_VERIFICATION", "BLOCKED", "FAILED"].map((st) => (
            <button
              key={st}
              className={`btn btn-secondary ${filterState === st ? "btn-primary" : ""}`}
              style={{ padding: "6px 12px", fontSize: "0.82rem" }}
              onClick={() => setFilterState(st)}
            >
              {st === "" ? "All States" : st.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="table-responsive">
          <table>
            <thead>
              <tr>
                <th>Payment Reference</th>
                <th>Recipient</th>
                <th>Amount</th>
                <th>State</th>
                <th>Risk Band (Score)</th>
                <th>Created At</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "40px 20px", color: "var(--text-muted)" }}>
                    Loading payment audit history...
                  </td>
                </tr>
              ) : filteredPayments.length > 0 ? (
                filteredPayments.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => onSelectTransaction(p)}
                    style={{ cursor: "pointer" }}
                    title="Click for full audit detail"
                  >
                    <td style={{ fontFamily: "monospace", fontSize: "0.85rem", color: "var(--primary)" }}>
                      {p.reference}
                    </td>
                    <td><strong>{p.recipient_upi}</strong></td>
                    <td style={{ fontWeight: 600 }}>
                      ₹{p.amount.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td>{renderStatusBadge(p.state)}</td>
                    <td>{renderRiskBadge(p.risk_assessment)}</td>
                    <td style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
                      {new Date(p.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "40px 20px", color: "var(--text-muted)" }}>
                    No payment attempts found matching criteria.
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
