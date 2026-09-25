import React from "react";
import { ShieldCheck, Send, LayoutDashboard, History, Settings, LogOut, User as UserIcon } from "lucide-react";

export default function Navbar({ activeTab, setActiveTab, user, onLogout, onOpenAuth }) {
  return (
    <header className="navbar">
      <div className="nav-brand">
        <div className="nav-brand-logo">
          <ShieldCheck size={20} />
        </div>
        <span>Yogii</span>
        <span className="badge badge-medium" style={{ fontSize: "0.68rem" }}>Demo / Sim</span>
      </div>

      <nav className="nav-links">
        <button
          className={`nav-btn ${activeTab === "dashboard" ? "active" : ""}`}
          onClick={() => setActiveTab("dashboard")}
        >
          <LayoutDashboard size={17} /> Dashboard
        </button>
        <button
          className={`nav-btn ${activeTab === "send" ? "active" : ""}`}
          onClick={() => setActiveTab("send")}
        >
          <Send size={17} /> Send Money
        </button>
        <button
          className={`nav-btn ${activeTab === "history" ? "active" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          <History size={17} /> History
        </button>
        <button
          className={`nav-btn ${activeTab === "settings" ? "active" : ""}`}
          onClick={() => setActiveTab("settings")}
        >
          <Settings size={17} /> Settings
        </button>
      </nav>

      <div className="nav-user">
        {user ? (
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ textAlign: "right", fontSize: "0.85rem" }}>
              <div style={{ fontWeight: 600, color: "var(--text-main)" }}>{user.full_name}</div>
              <div style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>{user.upi_id}</div>
            </div>
            <button
              className="btn btn-secondary"
              style={{ padding: "6px 12px", fontSize: "0.82rem" }}
              onClick={onLogout}
              title="Sign Out"
            >
              <LogOut size={15} /> Sign Out
            </button>
          </div>
        ) : (
          <button className="btn btn-primary" onClick={onOpenAuth}>
            <UserIcon size={16} /> Sign In
          </button>
        )}
      </div>
    </header>
  );
}
