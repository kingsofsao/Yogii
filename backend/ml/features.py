"""Pure feature computation, shared by the live API and the training pipeline.

The API (backend/ml/feature_engine.py) and the synthetic training pipeline
(backend/ml/synthetic_data.py) both call `compute_features`, so there is one
definition of every feature and no train/serve skew. Features only look at
events strictly before the payment being assessed, so they cannot leak the
future.

Features are signals. They do not say a person is guilty or a payment is
fraudulent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from backend.ml.graph_engine import GraphSignals

FEATURE_SCHEMA_VERSION = "v2"
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
COLD_START_AVG = 1000.0       # baseline when a sender has too little history
MIN_HISTORY_FOR_BASELINE = 3
NO_CHAIN_GAP_MINUTES = 1440.0

FEATURE_COLUMNS: List[str] = [
    # amount vs the sender's usual range
    "amount", "amount_log", "sender_avg_amount", "sender_median_amount",
    "amount_ratio_avg", "amount_ratio_median", "amount_zscore",
    "sender_history_count", "history_missing",
    # recipient familiarity
    "is_new_recipient", "prior_pair_count", "is_p2m",
    # velocity
    "tx_count_30m", "tx_value_30m_ratio", "tx_count_24h", "tx_value_24h_ratio", "velocity_ratio_24h",
    # time, device, location (device/location are simulated signals)
    "hour_deviation", "unusual_hour", "device_novelty", "location_novelty",
    # receiver summaries (aggregates only; never shown to the sender)
    "receiver_is_registered", "receiver_on_watchlist", "receiver_account_age_days",
    "receiver_distinct_senders_24h", "receiver_inflow_count_24h", "receiver_outflow_ratio_24h",
    # transaction graph
    "graph_hop_count", "graph_amount_similarity", "graph_time_gap_minutes",
    "graph_pass_through_flag", "graph_indirect_link",
]


@dataclass(frozen=True)
class PastPayment:
    """One earlier completed (or pending) outgoing payment by the sender."""
    at: datetime
    amount: float
    recipient_hash: str
    device_hash: Optional[str] = None
    location_hash: Optional[str] = None


@dataclass(frozen=True)
class ReceiverStats:
    is_registered: bool = False          # known Yogii user or directory payee
    on_watchlist: bool = False
    account_age_days: Optional[float] = None
    distinct_senders_24h: int = 0        # other payers in the last 24 hours
    inflow_count_24h: int = 0
    inflow_value_24h: float = 0.0
    outflow_value_24h: float = 0.0       # only known for Yogii users


@dataclass(frozen=True)
class PaymentContext:
    amount: float
    at: datetime
    recipient_hash: str
    payment_type: str = "P2P"
    device_hash: Optional[str] = None
    location_hash: Optional[str] = None


def local_hour(at: datetime) -> float:
    t = at.astimezone(LOCAL_TZ)
    return t.hour + t.minute / 60.0


def circular_mean_hour(hours: Sequence[float]) -> float:
    s = sum(math.sin(h / 24 * 2 * math.pi) for h in hours)
    c = sum(math.cos(h / 24 * 2 * math.pi) for h in hours)
    ang = math.atan2(s, c)
    if ang < 0:
        ang += 2 * math.pi
    return ang / (2 * math.pi) * 24


def circular_distance(a: float, b: float) -> float:
    d = abs(a - b) % 24
    return min(d, 24 - d)


def compute_features(ctx: PaymentContext, sender_history: Sequence[PastPayment], receiver: ReceiverStats,
                     graph: GraphSignals, window_days: int = 30) -> Dict[str, float]:
    """Build the model's feature vector.

    `sender_history` may contain up to 90 days of the sender's earlier
    outgoing payments; anything at or after `ctx.at` is ignored.
    `window_days` (7, 30 or 90) sets the baseline for the usual amount range.
    """
    at = ctx.at
    past = [p for p in sender_history if p.at < at and at - p.at <= timedelta(days=90)]
    window = [p for p in past if at - p.at <= timedelta(days=window_days)]
    amounts = [p.amount for p in window]

    history_missing = len(amounts) < MIN_HISTORY_FOR_BASELINE
    if history_missing:
        avg = med = COLD_START_AVG
        std = COLD_START_AVG * 0.5
    else:
        avg = sum(amounts) / len(amounts)
        med = float(median(amounts))
        std = math.sqrt(sum((a - avg) ** 2 for a in amounts) / len(amounts))

    amount = float(ctx.amount)
    prior_pair = sum(1 for p in past if p.recipient_hash == ctx.recipient_hash)
    last_30m = [p for p in past if at - p.at <= timedelta(minutes=30)]
    last_24h = [p for p in past if at - p.at <= timedelta(hours=24)]
    daily_rate = len(window) / float(window_days)

    hour = local_hour(at)
    hours = [local_hour(p.at) for p in past]
    hour_dev = circular_distance(hour, circular_mean_hour(hours)) if len(hours) >= MIN_HISTORY_FOR_BASELINE else 0.0

    known_devices = {p.device_hash for p in past if p.device_hash}
    known_locations = {p.location_hash for p in past if p.location_hash}
    device_novel = bool(ctx.device_hash and known_devices and ctx.device_hash not in known_devices)
    location_novel = bool(ctx.location_hash and known_locations and ctx.location_hash not in known_locations)

    inflow = receiver.inflow_value_24h
    outflow_ratio = (receiver.outflow_value_24h / inflow) if inflow > 0 else 0.0
    age = receiver.account_age_days

    return {
        "amount": round(amount, 2),
        "amount_log": math.log1p(amount),
        "sender_avg_amount": round(avg, 2),
        "sender_median_amount": round(med, 2),
        "amount_ratio_avg": amount / max(avg, 1.0),
        "amount_ratio_median": amount / max(med, 1.0),
        "amount_zscore": (amount - avg) / max(std, 0.25 * avg, 100.0),
        "sender_history_count": float(len(window)),
        "history_missing": 1.0 if history_missing else 0.0,
        "is_new_recipient": 1.0 if prior_pair == 0 else 0.0,
        "prior_pair_count": float(min(prior_pair, 50)),
        "is_p2m": 1.0 if ctx.payment_type == "P2M" else 0.0,
        "tx_count_30m": float(len(last_30m)),
        "tx_value_30m_ratio": sum(p.amount for p in last_30m) / max(avg, 100.0),
        "tx_count_24h": float(len(last_24h)),
        "tx_value_24h_ratio": sum(p.amount for p in last_24h) / max(avg, 100.0),
        "velocity_ratio_24h": len(last_24h) / max(daily_rate, 0.2),
        "hour_deviation": hour_dev,
        "unusual_hour": 1.0 if hour < 5 else 0.0,
        "device_novelty": 1.0 if device_novel else 0.0,
        "location_novelty": 1.0 if location_novel else 0.0,
        "receiver_is_registered": 1.0 if receiver.is_registered else 0.0,
        "receiver_on_watchlist": 1.0 if receiver.on_watchlist else 0.0,
        "receiver_account_age_days": float(min(age, 365.0)) if age is not None else -1.0,
        "receiver_distinct_senders_24h": float(min(receiver.distinct_senders_24h, 50)),
        "receiver_inflow_count_24h": float(min(receiver.inflow_count_24h, 100)),
        "receiver_outflow_ratio_24h": min(outflow_ratio, 5.0),
        "graph_hop_count": float(graph.hop_count),
        "graph_amount_similarity": graph.amount_similarity,
        "graph_time_gap_minutes": graph.time_gap_minutes if graph.time_gap_minutes is not None else NO_CHAIN_GAP_MINUTES,
        "graph_pass_through_flag": 1.0 if graph.pass_through else 0.0,
        "graph_indirect_link": 1.0 if graph.indirect_link else 0.0,
    }
