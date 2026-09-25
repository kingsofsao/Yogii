from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import numpy as np
from sqlalchemy.orm import Session
from backend.database.models import PaymentAttempt, Recipient, User
from backend.ml.graph_engine import TransactionGraphEngine

# Strict feature schema order required by XGBoost model
FEATURE_COLUMNS = [
    "amount",
    "avg_amount_30d",
    "median_amount_30d",
    "amount_ratio_avg",
    "amount_deviation_score",
    "is_new_recipient",
    "is_familiar_recipient",
    "prior_recipient_tx_count",
    "tx_count_30m",
    "tx_value_30m",
    "tx_count_24h",
    "tx_value_24h",
    "tx_count_7d",
    "tx_value_7d",
    "unusual_hour",
    "simulated_location_novelty",
    "simulated_device_novelty",
    "short_vs_long_velocity_ratio",
    "receiver_activity_score",
    "graph_hop_count",
    "graph_amount_similarity",
    "graph_time_gap_hours",
    "graph_pass_through_flag"
]

class FeatureEngine:
    """
    Transforms proposed transaction context and permitted historical data
    into a structured, model-ready feature vector.
    
    Privacy and Integrity:
    - Never processes or retains authentication secrets.
    - Handles users with zero transaction history gracefully using prior defaults.
    - Operates with historical windows (30m, 24h, 7d, 30d, 90d).
    """

    def __init__(self, graph_engine: Optional[TransactionGraphEngine] = None):
        self.graph_engine = graph_engine or TransactionGraphEngine()

    def build_features(
        self,
        db: Session,
        sender_user_id: int,
        recipient_lookup_hash: str,
        amount: float,
        timestamp: Optional[datetime] = None,
        device_id: Optional[str] = "demo-device",
        location: Optional[str] = "Chennai"
    ) -> Dict[str, float]:
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Fetch completed historical payments for sender (up to 90 days)
        cutoff_90d = now - timedelta(days=90)
        history_query = (
            db.query(PaymentAttempt)
            .filter(
                PaymentAttempt.sender_user_id == sender_user_id,
                PaymentAttempt.state == "COMPLETED",
                PaymentAttempt.created_at >= cutoff_90d
            )
            .order_by(PaymentAttempt.created_at.desc())
            .all()
        )

        amounts_30d = []
        amounts_7d = []
        tx_count_30m = 0
        tx_value_30m = 0.0
        tx_count_24h = 0
        tx_value_24h = 0.0
        tx_count_7d = 0
        tx_value_7d = 0.0

        prior_recipient_count = 0
        seen_devices = set()
        seen_locations = set()

        cutoff_30m = now - timedelta(minutes=30)
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)

        for tx in history_query:
            tx_time = tx.created_at
            if tx_time.tzinfo is None:
                tx_time = tx_time.replace(tzinfo=timezone.utc)

            amt = float(tx.amount)

            # Recipient matching
            if tx.recipient_upi_lookup_hash == recipient_lookup_hash:
                prior_recipient_count += 1

            # Time windows
            if tx_time >= cutoff_30m:
                tx_count_30m += 1
                tx_value_30m += amt

            if tx_time >= cutoff_24h:
                tx_count_24h += 1
                tx_value_24h += amt

            if tx_time >= cutoff_7d:
                tx_count_7d += 1
                tx_value_7d += amt
                amounts_7d.append(amt)

            if tx_time >= cutoff_30d:
                amounts_30d.append(amt)

        # 2. Historical amount metrics (30-day baseline)
        if amounts_30d:
            avg_amount_30d = float(np.mean(amounts_30d))
            median_amount_30d = float(np.median(amounts_30d))
            std_amount = float(np.std(amounts_30d)) if len(amounts_30d) > 1 else avg_amount_30d * 0.3
        else:
            # Default cold-start baseline for accounts without prior completed payments
            avg_amount_30d = 1000.0
            median_amount_30d = 800.0
            std_amount = 500.0

        amount_ratio_avg = float(amount) / max(avg_amount_30d, 1.0)
        amount_deviation_score = max(0.0, (float(amount) - avg_amount_30d) / max(std_amount, 100.0))

        # 3. Recipient Familiarity
        is_new_recipient = 1.0 if prior_recipient_count == 0 else 0.0
        is_familiar_recipient = 1.0 if prior_recipient_count >= 3 else 0.0

        # 4. Contextual signals
        unusual_hour = 1.0 if (now.hour < 6 or now.hour >= 23) else 0.0
        
        # Location & Device Novelty (demo logic: check if non-standard or unusual)
        simulated_location_novelty = 1.0 if location and location.lower() not in ("chennai", "mumbai", "delhi", "bengaluru") else 0.0
        simulated_device_novelty = 1.0 if device_id and device_id.startswith("untrusted-") else 0.0

        # Short-term vs long-term velocity ratio
        daily_rate_from_7d = (tx_count_7d / 7.0) if tx_count_7d > 0 else 0.5
        short_vs_long_velocity_ratio = float(tx_count_24h) / max(daily_rate_from_7d, 0.1)

        # 5. Receiver Activity Signals
        # Count transactions received by this recipient from all users
        receiver_history = (
            db.query(PaymentAttempt)
            .filter(
                PaymentAttempt.recipient_upi_lookup_hash == recipient_lookup_hash,
                PaymentAttempt.state == "COMPLETED"
            )
            .count()
        )
        receiver_activity_score = min(float(receiver_history) / 10.0, 1.0)

        # 6. Graph Features
        self.graph_engine.load_from_db(db)
        sender_node = f"user:{sender_user_id}"
        target_node = f"upi:{recipient_lookup_hash[:16]}"

        pass_through_info = self.graph_engine.detect_pass_through_pattern(
            sender_node=sender_node,
            target_node=target_node,
            proposed_amount=float(amount)
        )

        graph_pass_through_flag = 1.0 if pass_through_info["possible_pass_through"] else 0.0
        graph_hop_count = float(pass_through_info["hop_count"])
        graph_amount_similarity = float(pass_through_info["amount_similarity"])
        graph_time_gap_hours = (
            float(pass_through_info["time_gap_minutes"]) / 60.0
            if pass_through_info["time_gap_minutes"] is not None
            else 24.0
        )

        features: Dict[str, float] = {
            "amount": float(amount),
            "avg_amount_30d": round(avg_amount_30d, 2),
            "median_amount_30d": round(median_amount_30d, 2),
            "amount_ratio_avg": round(amount_ratio_avg, 3),
            "amount_deviation_score": round(amount_deviation_score, 3),
            "is_new_recipient": is_new_recipient,
            "is_familiar_recipient": is_familiar_recipient,
            "prior_recipient_tx_count": float(prior_recipient_count),
            "tx_count_30m": float(tx_count_30m),
            "tx_value_30m": float(tx_value_30m),
            "tx_count_24h": float(tx_count_24h),
            "tx_value_24h": float(tx_value_24h),
            "tx_count_7d": float(tx_count_7d),
            "tx_value_7d": float(tx_value_7d),
            "unusual_hour": unusual_hour,
            "simulated_location_novelty": simulated_location_novelty,
            "simulated_device_novelty": simulated_device_novelty,
            "short_vs_long_velocity_ratio": round(short_vs_long_velocity_ratio, 3),
            "receiver_activity_score": round(receiver_activity_score, 2),
            "graph_hop_count": graph_hop_count,
            "graph_amount_similarity": round(graph_amount_similarity, 3),
            "graph_time_gap_hours": round(graph_time_gap_hours, 2),
            "graph_pass_through_flag": graph_pass_through_flag
        }

        return features
