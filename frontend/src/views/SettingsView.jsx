import React, { useState, useEffect } from "react";
import { Shield, Lock, Cpu, Info, AlertTriangle, CheckCircle2 } from "lucide-react";
import { apiRequest } from "../api/client";

export default function SettingsView({ user }) {
  const [modelInfo, setModelInfo] = useState(null);
  const [appSettings, setAppSettings] = useState(null);
  const [liveToggleError, setLiveToggleError] = useState("");

  useEffect(() => {
    fetchInfo();
  }, []);

  async function fetchInfo() {
    try {
      const [m, s] = await Promise.all([
        apiRequest("/model/info"),
        apiRequest("/settings")
      ]);
      setModelInfo(m);
      setAppSettings(s);
    } catch (err) {
      console.error("Failed to fetch settings/model info:", err);
    }
  }

  async function attemptLiveToggle() {
    setLiveToggleError("");
    try {
      await apiRequest("/settings", {
        method: "PATCH",
        body: JSON.stringify({ live_upi_enabled: true })
      });
    } catch (err) {
      setLiveToggleError(err.message);
    }
  }

  return (
    <div style={{ maxWidth: "720px", margin: "0 auto" }}>
      <div style={{ marginBottom: "20px" }}>
        <h1 style={{ fontSize: "1.35rem", fontWeight: 700 }}>Security &amp; System Configuration</h1>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          Inspect Yogii cryptographic protection, ML model parameters, and simulation policies.
        </p>
      </div>

      {/* User Security Profile */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "1rem", marginBottom: "14px" }}>
          <Lock size={18} color="var(--primary)" />
          <span>Application-Level Cryptographic Security</span>
        </div>

        <div style={{ fontSize: "0.88rem", color: "var(--text-muted)", lineHeight: 1.6, marginBottom: "16px" }}>
          Yogii enforces zero-plaintext database storage for sensitive personal identifiers:
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "0.85rem" }}>
          <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
            <strong>Reversible PII Encryption:</strong>
            <div style={{ color: "var(--text-muted)", marginTop: "2px" }}>AES-256-GCM with fresh 96-bit nonces</div>
          </div>
          <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
            <strong>Searchable Equality:</strong>
            <div style={{ color: "var(--text-muted)", marginTop: "2px" }}>HMAC-SHA-256 blind indexing</div>
          </div>
          <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
            <strong>Password Hash Algorithm:</strong>
            <div style={{ color: "var(--text-muted)", marginTop: "2px" }}>Argon2id (time=2, mem=19MiB)</div>
          </div>
          <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
            <strong>Payment Auth Secrets:</strong>
            <div style={{ color: "var(--text-muted)", marginTop: "2px" }}>NEVER collected, stored, or logged</div>
          </div>
        </div>
      </div>

      {/* Live UPI Rail Feature Flag Guard */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "1rem", marginBottom: "8px" }}>
          <Shield size={18} color="var(--warning)" />
          <span>Payment Rail Configuration</span>
        </div>

        <div style={{ fontSize: "0.88rem", color: "var(--text-muted)", marginBottom: "16px" }}>
          Current Mode: <strong style={{ color: "var(--primary)" }}>{appSettings?.payment_mode || "simulation"}</strong>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px", background: "var(--bg-muted)", borderRadius: "8px", marginBottom: "12px" }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Enable Production Live UPI Rail</div>
            <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
              Requires NPCI TPAP registration &amp; Sponsor-Bank authorization
            </div>
          </div>
          <button className="btn btn-secondary" onClick={attemptLiveToggle} style={{ fontSize: "0.82rem" }}>
            Attempt Enable
          </button>
        </div>

        {liveToggleError && (
          <div style={{ padding: "10px 14px", background: "var(--danger-bg)", color: "#b91c1c", borderRadius: "8px", fontSize: "0.82rem", border: "1px solid #fecaca" }}>
            <strong>Safety Invariant Enforced:</strong> {liveToggleError}
          </div>
        )}
      </div>

      {/* Fraud Model Inspection */}
      {modelInfo && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "1rem", marginBottom: "12px" }}>
            <Cpu size={18} color="var(--primary)" />
            <span>Fraud Risk Intelligence Model</span>
          </div>

          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "16px" }}>
            {modelInfo.disclaimer}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "10px", textAlign: "center", marginBottom: "16px" }}>
            <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>PR-AUC</div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{modelInfo.metrics?.pr_auc}</div>
            </div>
            <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>F1 Score</div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{modelInfo.metrics?.f1}</div>
            </div>
            <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Precision</div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{modelInfo.metrics?.precision}</div>
            </div>
            <div style={{ padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Recall</div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{modelInfo.metrics?.recall}</div>
            </div>
          </div>

          <div style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
            Algorithm: <strong>{modelInfo.algorithm}</strong> &bull; Version: <strong>{modelInfo.model_version}</strong> &bull; Schema: <strong>{modelInfo.feature_schema_version} ({modelInfo.feature_columns?.length} features)</strong>
          </div>
        </div>
      )}
    </div>
  );
}
