"""Compare Yogii's payment records with the rail's view for one day.

With the mock rail this is a per-payment status comparison. A real sponsor
bank adapter would use the bank's settlement files via
`PaymentProvider.fetch_settlement_records`, in the format the bank documents.
The report lists mismatches for a person to investigate; it never edits
balances by itself.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.database.models import PaymentAttempt
from backend.integrations.payments import PaymentProvider, ProviderError, ProviderStatus

_EXPECTED = {"COMPLETED": ProviderStatus.SUCCESS, "FAILED": ProviderStatus.FAILED, "PENDING": ProviderStatus.PENDING,
             "REVERSED": ProviderStatus.REVERSED}


def reconcile_day(db: Session, provider: PaymentProvider, day: date) -> Dict:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    rows = (db.query(PaymentAttempt)
            .filter(PaymentAttempt.provider_reference.isnot(None),
                    PaymentAttempt.created_at >= start, PaymentAttempt.created_at < start + timedelta(days=1))
            .all())
    mismatches: List[Dict] = []
    for p in rows:
        try:
            status = provider.get_payment_status(p.provider_reference).status
        except ProviderError as exc:
            mismatches.append({"reference": p.reference, "yogii_state": p.state, "rail_status": f"ERROR: {exc}"})
            continue
        expected = _EXPECTED.get(p.state)
        # A pending payment that the rail now reports as settled is expected to catch up on the next lookup.
        if expected != status and not (p.state == "PENDING" and status == ProviderStatus.SUCCESS):
            mismatches.append({"reference": p.reference, "yogii_state": p.state, "rail_status": status.value})
    return {"batch_date": day.isoformat(), "provider": provider.name, "checked": len(rows),
            "mismatches": mismatches, "is_simulated": not provider.is_live}
