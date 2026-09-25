import React, { useState } from "react";
import { X, Lock, Mail, User, Phone, CheckCircle, Shield } from "lucide-react";
import { apiRequest, setAuthToken } from "../api/client";

export default function AuthModal({ isOpen, onClose, onAuthSuccess }) {
  const [tab, setTab] = useState("login"); // 'login' | 'register'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Login form state
  const [loginIdentifier, setLoginIdentifier] = useState("yogesh@yogii");
  const [loginPassword, setLoginPassword] = useState("Password123!");

  // Registration form state
  const [regFullName, setRegFullName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPhone, setRegPhone] = useState("");
  const [regUpiId, setRegUpiId] = useState("");
  const [regPassword, setRegPassword] = useState("");

  if (!isOpen) return null;

  async function handleLogin(e) {
    if (e) e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email_or_phone_or_upi: loginIdentifier.trim(),
          password: loginPassword
        })
      });
      setAuthToken(data.access_token);
      onAuthSuccess(data.user);
      onClose();
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e) {
    if (e) e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await apiRequest("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: regFullName.trim(),
          email: regEmail.trim(),
          phone: regPhone.trim(),
          upi_id: regUpiId.trim(),
          password: regPassword
        })
      });
      setAuthToken(data.access_token);
      onAuthSuccess(data.user);
      onClose();
    } catch (err) {
      setError(err.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  function applyPreset(name, email, phone, upi) {
    setLoginIdentifier(upi);
    setLoginPassword("Password123!");
    setTab("login");
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: "480px" }}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
            <Shield size={20} color="var(--primary)" />
            <span>{tab === "login" ? "Sign In to Yogii" : "Create Demo Account"}</span>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          <button
            style={{
              flex: 1,
              padding: "12px",
              background: tab === "login" ? "#fff" : "var(--bg-muted)",
              border: "none",
              borderBottom: tab === "login" ? "2px solid var(--primary)" : "none",
              fontWeight: 600,
              cursor: "pointer",
              color: tab === "login" ? "var(--primary)" : "var(--text-muted)"
            }}
            onClick={() => setTab("login")}
          >
            Sign In
          </button>
          <button
            style={{
              flex: 1,
              padding: "12px",
              background: tab === "register" ? "#fff" : "var(--bg-muted)",
              border: "none",
              borderBottom: tab === "register" ? "2px solid var(--primary)" : "none",
              fontWeight: 600,
              cursor: "pointer",
              color: tab === "register" ? "var(--primary)" : "var(--text-muted)"
            }}
            onClick={() => setTab("register")}
          >
            Register
          </button>
        </div>

        <div className="modal-body">
          {/* Quick Demo Fill Buttons */}
          <div style={{ marginBottom: "16px", padding: "10px", background: "var(--bg-muted)", borderRadius: "8px" }}>
            <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "6px" }}>
              Quick Select Demo Persona:
            </div>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "0.78rem" }}
                onClick={() => applyPreset("Yogesh", "yogesh@demo.yogii", "9876543210", "yogesh@yogii")}
              >
                Yogesh (Routine)
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "0.78rem" }}
                onClick={() => applyPreset("Visrojit", "visrojit@demo.yogii", "9876543211", "visrojit@yogii")}
              >
                Visrojit (Intermediary)
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "0.78rem" }}
                onClick={() => applyPreset("Dinesh", "dinesh@demo.yogii", "9876543212", "dinesh@yogii")}
              >
                Dinesh (Recipient)
              </button>
            </div>
          </div>

          {error && (
            <div style={{ padding: "10px 14px", background: "var(--danger-bg)", color: "#b91c1c", borderRadius: "8px", fontSize: "0.85rem", marginBottom: "16px" }}>
              {error}
            </div>
          )}

          {tab === "login" ? (
            <form onSubmit={handleLogin}>
              <div className="form-group">
                <label className="form-label">UPI ID, Email, or Phone</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  value={loginIdentifier}
                  onChange={(e) => setLoginIdentifier(e.target.value)}
                  placeholder="e.g. yogesh@yogii or 9876543210"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Password</label>
                <input
                  type="password"
                  className="form-input"
                  required
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  placeholder="Demo password: Password123!"
                />
              </div>

              <button type="submit" className="btn btn-primary" style={{ width: "100%", marginTop: "10px" }} disabled={loading}>
                {loading ? "Authenticating..." : "Sign In to Simulated Account"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleRegister}>
              <div className="form-group">
                <label className="form-label">Full Name</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  value={regFullName}
                  onChange={(e) => setRegFullName(e.target.value)}
                  placeholder="e.g. Anand Sharma"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Email Address</label>
                <input
                  type="email"
                  className="form-input"
                  required
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  placeholder="e.g. anand@demo.yogii"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Phone Number (10 digits)</label>
                <input
                  type="tel"
                  className="form-input"
                  required
                  value={regPhone}
                  onChange={(e) => setRegPhone(e.target.value)}
                  placeholder="e.g. 9812345678"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Simulated UPI ID</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  value={regUpiId}
                  onChange={(e) => setRegUpiId(e.target.value)}
                  placeholder="e.g. anand@yogii"
                />
              </div>

              <div className="form-group">
                <label className="form-label">Password (min 8 chars)</label>
                <input
                  type="password"
                  className="form-input"
                  required
                  minLength={8}
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  placeholder="Create a password"
                />
              </div>

              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "12px" }}>
                🔒 Never enter real bank credentials, UPI PINs, or OTPs. All data is encrypted with AES-256-GCM.
              </div>

              <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={loading}>
                {loading ? "Creating Account..." : "Create Simulated Account"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
