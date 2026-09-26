"""Apply the data-retention policy (see docs/SECURITY_AND_PRIVACY.md).

    python -m backend.scripts.retention [--dry-run]

Deletes, older than the configured number of days:
* feature snapshots (RETENTION_FEATURE_SNAPSHOT_DAYS, default 180)
* security events (RETENTION_SECURITY_EVENT_DAYS, default 365)
* transaction-graph edges (RETENTION_GRAPH_EDGE_DAYS, default 90; the model only looks back 90 days)

Payment attempts, risk assessments and audit events are kept as the payment
record. A real deployment must set these periods from the sponsor bank's and
the applicable legal requirements, not from these prototype defaults.
"""

import argparse
from datetime import datetime, timedelta, timezone

from backend.core.config import settings
from backend.database.database import SessionLocal
from backend.database.models import FeatureSnapshot, SecurityEvent, TransactionGraphEdge

RULES = [
    (FeatureSnapshot, FeatureSnapshot.created_at, "RETENTION_FEATURE_SNAPSHOT_DAYS"),
    (SecurityEvent, SecurityEvent.created_at, "RETENTION_SECURITY_EVENT_DAYS"),
    (TransactionGraphEdge, TransactionGraphEdge.timestamp, "RETENTION_GRAPH_EDGE_DAYS"),
]


def apply_retention(dry_run: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    report = {}
    try:
        for model, column, setting in RULES:
            cutoff = now - timedelta(days=getattr(settings, setting))
            q = db.query(model).filter(column < cutoff)
            report[model.__tablename__] = q.count() if dry_run else q.delete(synchronize_session=False)
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(("Would delete" if args.dry_run else "Deleted"), apply_retention(args.dry_run))
