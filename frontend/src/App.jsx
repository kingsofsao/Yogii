import React, { useState, useEffect } from "react";
import SimulatedNoticeBanner from "./components/SimulatedNoticeBanner";
import Navbar from "./components/Navbar";
import AuthModal from "./components/AuthModal";
import DashboardView from "./views/DashboardView";
import SendMoneyView from "./views/SendMoneyView";
import HistoryView from "./views/HistoryView";
import SettingsView from "./views/SettingsView";
import TransactionDetailModal from "./views/TransactionDetailModal";
import { apiRequest, getAuthToken, clearAuthToken } from "./api/client";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [user, setUser] = useState(null);
  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [selectedTx, setSelectedTx] = useState(null);
  const [initialRecipientForSend, setInitialRecipientForSend] = useState("rahul@upi");

  useEffect(() => {
    // Listen for 401 unauthorized events
    const handleUnauthorized = () => {
      setUser(null);
      setDashboardData(null);
      setIsAuthOpen(true);
    };
    window.addEventListener("yogii_unauthorized", handleUnauthorized);

    initSession();

    return () => window.removeEventListener("yogii_unauthorized", handleUnauthorized);
  }, []);

  async function initSession() {
    const token = getAuthToken();
    if (!token) {
      // Auto-open auth dialog or try demo login if first visit
      setLoading(false);
      setIsAuthOpen(true);
      return;
    }

    await refreshDashboard();
  }

  async function refreshDashboard() {
    try {
      setLoading(true);
      const data = await apiRequest("/dashboard");
      setDashboardData(data);
      setUser(data.user);
    } catch (err) {
      console.warn("Session check failed or unauthenticated:", err);
      clearAuthToken();
      setUser(null);
      setDashboardData(null);
      setIsAuthOpen(true);
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    clearAuthToken();
    setUser(null);
    setDashboardData(null);
    setActiveTab("dashboard");
    setIsAuthOpen(true);
  }

  function handleAuthSuccess(userData) {
    setUser(userData);
    refreshDashboard();
  }

  function handleNavigateToSend(recipientUpi) {
    if (recipientUpi) {
      setInitialRecipientForSend(recipientUpi);
    }
    setActiveTab("send");
  }

  return (
    <div className="app-container">
      {/* Persistent Simulation Notice Banner */}
      <SimulatedNoticeBanner />

      {/* Main Navigation */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        user={user}
        onLogout={handleLogout}
        onOpenAuth={() => setIsAuthOpen(true)}
      />

      {/* Main Content Area */}
      <main className="main-content">
        {!user && !loading && (
          <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
            <h2 style={{ fontSize: "1.3rem", fontWeight: 700, marginBottom: "8px" }}>
              Welcome to Yogii Payment Simulation Platform
            </h2>
            <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", maxWidth: "480px", margin: "0 auto 20px" }}>
              Sign in with a pre-seeded demo user (Yogesh, Visrojit, or Dinesh) or create a fresh simulated demo profile to test the XGBoost fraud risk intelligence system.
            </p>
            <button className="btn btn-primary" onClick={() => setIsAuthOpen(true)}>
              Sign In to Demo Account
            </button>
          </div>
        )}

        {user && activeTab === "dashboard" && (
          <DashboardView
            dashboardData={dashboardData}
            onNavigateToSend={handleNavigateToSend}
            onSelectTransaction={(tx) => setSelectedTx(tx)}
          />
        )}

        {user && activeTab === "send" && (
          <SendMoneyView
            initialRecipient={initialRecipientForSend}
            balance={dashboardData?.simulated_balance || 0}
            onPaymentCompleted={() => refreshDashboard()}
          />
        )}

        {user && activeTab === "history" && (
          <HistoryView
            onSelectTransaction={(tx) => setSelectedTx(tx)}
          />
        )}

        {user && activeTab === "settings" && (
          <SettingsView user={user} />
        )}
      </main>

      {/* Auth Modal */}
      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onAuthSuccess={handleAuthSuccess}
      />

      {/* Transaction Risk Audit Detail Modal */}
      <TransactionDetailModal
        transaction={selectedTx}
        onClose={() => setSelectedTx(null)}
      />
    </div>
  );
}
