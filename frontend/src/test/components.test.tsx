import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RiskCard from "../components/RiskCard";
import SimulationBanner from "../components/SimulationBanner";
import { RiskBadge } from "../components/ui";
import { risk } from "./utils";

describe("components", () => {
  it("simulation banner states that nothing is real", () => {
    render(<SimulationBanner />);
    const note = screen.getByRole("note", { name: /simulation notice/i });
    expect(note).toHaveTextContent(/No real money moves/);
    expect(note).toHaveTextContent(/not connected to UPI, NPCI or any bank/);
  });

  it("risk card shows score, band, reasons and the synthetic-data disclaimer", () => {
    render(<RiskCard risk={risk("HIGH", 72, ["AMOUNT_ABOVE_USUAL", "NEW_RECIPIENT"]) as never} />);
    expect(screen.getByTestId("risk-score")).toHaveTextContent("72");
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /why this risk level/i }).children).toHaveLength(2);
    expect(screen.getByText(/synthetic data/)).toHaveTextContent(/not RBI, NPCI or bank standards/);
  });

  it("risk card says when nothing stood out", () => {
    render(<RiskCard risk={risk("LOW", 3) as never} />);
    expect(screen.getByText("Nothing unusual stood out.")).toBeInTheDocument();
  });

  it("badges have readable labels", () => {
    render(<RiskBadge band="VERY_HIGH" />);
    expect(screen.getByText("Very high risk")).toBeInTheDocument();
  });
});
