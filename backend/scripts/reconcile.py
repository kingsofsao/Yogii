"""Reconcile one day of payments against the payment rail.

    python -m backend.scripts.reconcile [YYYY-MM-DD]

Prints mismatches for a person to investigate. It never changes balances.
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone

from backend.database.database import SessionLocal
from backend.domain.reconciliation import reconcile_day
from backend.integrations.payments import build_payment_provider

if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else (datetime.now(timezone.utc) - timedelta(days=1)).date()
    db = SessionLocal()
    try:
        print(json.dumps(reconcile_day(db, build_payment_provider(), day), indent=2))
    finally:
        db.close()
