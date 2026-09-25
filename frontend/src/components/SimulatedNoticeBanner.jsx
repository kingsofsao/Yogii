import React from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";

export default function SimulatedNoticeBanner() {
  return (
    <div className="simulation-banner" role="alert">
      <span className="sim-pill">Simulated Environment</span>
      <AlertTriangle size={15} />
      <span>
        Yogii operates strictly in <strong>SIMULATION MODE</strong> for development & testing. 
        No real money or real UPI rails are utilized.
      </span>
    </div>
  );
}
