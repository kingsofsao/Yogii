"""Yogii prototype decision policy.

Bands (defaults, configurable on the backend through RISK_THRESHOLD_* settings):
    0-29   LOW        allow the simulated payment to continue
    30-59  MEDIUM     warn and require demo verification
    60-84  HIGH       strong warning and require demo verification
    85-100 VERY_HIGH  block the simulated payment before mock authorisation

A score driven only by transaction-graph signals is capped at HIGH (verify),
never blocked: a graph link is not proof.

These are Yogii prototype values chosen for a demo. They are not prescribed by
the RBI, NPCI or any bank. In a live deployment, the sponsor bank's approved
policy and the applicable UPI requirements are authoritative; Yogii's policy
could at most add friction before submission, never approve something the bank
declines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from backend.core.config import Settings, settings as default_settings


GRAPH_ONLY_CODES = frozenset({"POSSIBLE_PASS_THROUGH_PATTERN", "INDIRECT_TRANSACTION_LINK"})


@dataclass(frozen=True)
class PolicyDecision:
    band: str        # LOW, MEDIUM, HIGH, VERY_HIGH
    decision: str    # ALLOW, VERIFY, BLOCK
    requires_verification: bool
    blocked: bool


class RiskPolicy:
    def __init__(self, thresholds: Optional[Dict[str, int]] = None, version: Optional[str] = None,
                 cfg: Optional[Settings] = None):
        cfg = cfg or default_settings
        self.thresholds = dict(thresholds or cfg.risk_thresholds)
        self.version = version or cfg.RISK_POLICY_VERSION
        t = self.thresholds
        if not (0 < t["MEDIUM"] < t["HIGH"] < t["VERY_HIGH"] <= 100):
            raise ValueError("Risk thresholds must satisfy 0 < MEDIUM < HIGH < VERY_HIGH <= 100.")

    def band_for(self, score: int) -> str:
        t = self.thresholds
        if score >= t["VERY_HIGH"]:
            return "VERY_HIGH"
        if score >= t["HIGH"]:
            return "HIGH"
        if score >= t["MEDIUM"]:
            return "MEDIUM"
        return "LOW"

    def decide(self, score: int, reason_codes: Iterable[str] = ()) -> PolicyDecision:
        if not 0 <= score <= 100:
            raise ValueError("Risk score must be between 0 and 100.")
        band = self.band_for(score)
        codes = set(reason_codes)
        if band == "VERY_HIGH" and codes and codes <= GRAPH_ONLY_CODES:
            # A transaction-graph link is never proof on its own: without any other
            # signal, the strongest action is a warning with verification, not a block.
            return PolicyDecision("HIGH", "VERIFY", True, False)
        if band == "VERY_HIGH":
            return PolicyDecision(band, "BLOCK", False, True)
        if band in ("MEDIUM", "HIGH"):
            return PolicyDecision(band, "VERIFY", True, False)
        return PolicyDecision(band, "ALLOW", False, False)

    def describe(self) -> Dict[str, str]:
        t = self.thresholds
        return {
            "LOW": f"0-{t['MEDIUM'] - 1}: the simulated payment can continue",
            "MEDIUM": f"{t['MEDIUM']}-{t['HIGH'] - 1}: warning and demo verification",
            "HIGH": f"{t['HIGH']}-{t['VERY_HIGH'] - 1}: strong warning and demo verification",
            "VERY_HIGH": f"{t['VERY_HIGH']}-100: the simulated payment is blocked",
        }
