"""Database adapter for the Feature Engine.

It gathers only what the model is permitted to use, then calls the pure
`compute_features` shared with training:
* the sender's own earlier payments (up to 90 days),
* aggregate counts about the receiver (never shown to the sender),
* transaction-graph edges from the last 90 days, keyed by hashed account ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.encryption import encryption_service
from backend.database.database import as_utc
from backend.database.models import PaymentAttempt, Recipient, TransactionGraphEdge, User, graph_node_for
from backend.ml.features import FEATURE_COLUMNS, PastPayment, PaymentContext, ReceiverStats, compute_features
from backend.ml.graph_engine import GraphEdge, GraphSignals, TransactionGraph

__all__ = ["FeatureEngine", "FEATURE_COLUMNS", "hash_signal", "ResolvedRecipient"]

GRAPH_EDGE_LIMIT = 50000


def hash_signal(kind: str, value: Optional[str]) -> Optional[str]:
    """Keyed hash for simulated device / location labels so raw values are never stored."""
    if not value:
        return None
    return encryption_service.blind_index(f"{kind}:{value.strip().lower()}")


@dataclass
class ResolvedRecipient:
    upi_hash: str
    kind: str                       # user, directory, unregistered
    payment_type: str               # P2P or P2M
    user: Optional[User] = None
    directory: Optional[Recipient] = None

    @property
    def is_registered(self) -> bool:
        return self.kind in ("user", "directory")

    @property
    def on_watchlist(self) -> bool:
        return bool(self.directory and self.directory.on_watchlist)

    @property
    def created_at(self) -> Optional[datetime]:
        if self.user is not None:
            return as_utc(self.user.created_at)
        if self.directory is not None:
            return as_utc(self.directory.created_at)
        return None


def resolve_recipient(db: Session, upi_hash: str) -> ResolvedRecipient:
    user = db.query(User).filter(User.upi_id_lookup_hash == upi_hash).first()
    if user:
        return ResolvedRecipient(upi_hash, "user", "P2P", user=user)
    rec = db.query(Recipient).filter(Recipient.upi_id_lookup_hash == upi_hash).first()
    if rec:
        return ResolvedRecipient(upi_hash, "directory", rec.recipient_type, directory=rec)
    return ResolvedRecipient(upi_hash, "unregistered", "P2P")


class FeatureEngine:
    def __init__(self, window_days: Optional[int] = None, graph_depth: Optional[int] = None):
        self.window_days = window_days or settings.FEATURE_HISTORY_DAYS
        self.graph_depth = graph_depth or settings.GRAPH_MAX_DEPTH

    def sender_history(self, db: Session, sender_user_id: int, at: datetime, exclude_id: Optional[int]):
        rows = (
            db.query(PaymentAttempt.created_at, PaymentAttempt.amount, PaymentAttempt.recipient_upi_lookup_hash,
                     PaymentAttempt.device_hash, PaymentAttempt.location_hash)
            .filter(PaymentAttempt.sender_user_id == sender_user_id,
                    PaymentAttempt.state.in_(("COMPLETED", "PENDING")),
                    PaymentAttempt.created_at >= at - timedelta(days=90),
                    PaymentAttempt.created_at < at)
        )
        if exclude_id is not None:
            rows = rows.filter(PaymentAttempt.id != exclude_id)
        return [PastPayment(as_utc(r[0]), float(r[1]), r[2], r[3], r[4]) for r in rows.all()]

    def receiver_stats(self, db: Session, recipient: ResolvedRecipient, sender_user_id: int, at: datetime) -> ReceiverStats:
        since = at - timedelta(hours=24)
        inbound = (
            db.query(PaymentAttempt.sender_user_id, PaymentAttempt.amount)
            .filter(PaymentAttempt.recipient_upi_lookup_hash == recipient.upi_hash,
                    PaymentAttempt.state == "COMPLETED",
                    PaymentAttempt.created_at >= since, PaymentAttempt.created_at < at)
            .all()
        )
        outflow = 0.0
        if recipient.user is not None:
            outflow = float(
                db.query(func.coalesce(func.sum(PaymentAttempt.amount), 0))
                .filter(PaymentAttempt.sender_user_id == recipient.user.id, PaymentAttempt.state == "COMPLETED",
                        PaymentAttempt.created_at >= since, PaymentAttempt.created_at < at)
                .scalar() or 0.0
            )
        created = recipient.created_at
        return ReceiverStats(
            is_registered=recipient.is_registered,
            on_watchlist=recipient.on_watchlist,
            account_age_days=(at - created).total_seconds() / 86400 if created else None,
            distinct_senders_24h=len({s for s, _ in inbound if s != sender_user_id}),
            inflow_count_24h=len(inbound),
            inflow_value_24h=float(sum(float(a) for _, a in inbound)),
            outflow_value_24h=outflow,
        )

    def graph_signals(self, db: Session, sender_node: str, recipient_node: str, amount: float, at: datetime,
                      exclude_payment_id: Optional[int]) -> GraphSignals:
        q = (db.query(TransactionGraphEdge)
             .filter(TransactionGraphEdge.timestamp >= at - timedelta(days=90), TransactionGraphEdge.timestamp < at)
             .order_by(TransactionGraphEdge.timestamp.desc()).limit(GRAPH_EDGE_LIMIT))
        edges = [GraphEdge(e.sender_node, e.receiver_node, float(e.amount), as_utc(e.timestamp), e.payment_id)
                 for e in q.all() if e.payment_id != exclude_payment_id]
        graph = TransactionGraph.from_edges(edges, self.graph_depth)
        return graph.signals_for(sender_node, recipient_node, amount, at, settings.GRAPH_WINDOW_MINUTES,
                                 settings.GRAPH_AMOUNT_TOLERANCE)

    def build(self, db: Session, sender: User, recipient: ResolvedRecipient, amount: float,
              at: Optional[datetime] = None, device_hash: Optional[str] = None,
              location_hash: Optional[str] = None, exclude_id: Optional[int] = None):
        """Return (features, graph_signals, receiver_stats)."""
        at = as_utc(at or datetime.now(timezone.utc))
        history = self.sender_history(db, sender.id, at, exclude_id)
        receiver = self.receiver_stats(db, recipient, sender.id, at)
        graph = self.graph_signals(db, sender.graph_node, graph_node_for(recipient.upi_hash), amount, at, exclude_id)
        ctx = PaymentContext(float(amount), at, recipient.upi_hash, recipient.payment_type, device_hash, location_hash)
        features: Dict[str, float] = compute_features(ctx, history, receiver, graph, self.window_days)
        return features, graph, receiver
