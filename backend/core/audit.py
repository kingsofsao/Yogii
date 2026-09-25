import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Structured logger for audit compliance
audit_logger = logging.getLogger("yogii.audit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

FORBIDDEN_KEYWORDS = {"pin", "upi_pin", "password", "cvv", "otp", "secret", "private_key", "credentials"}

def sanitize_metadata(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitizes metadata dictionary to ensure no authentication secrets or credentials are ever logged."""
    if not data:
        return {}
    clean = {}
    for k, v in data.items():
        key_lower = k.lower()
        if any(bad in key_lower for bad in FORBIDDEN_KEYWORDS):
            continue  # Completely scrub forbidden secret fields
        if isinstance(v, dict):
            clean[k] = sanitize_metadata(v)
        elif isinstance(v, list):
            clean[k] = [sanitize_metadata(item) if isinstance(item, dict) else item for item in v]
        else:
            clean[k] = v
    return clean

def log_audit_event(
    actor_id: Optional[str],
    action: str,
    resource: str,
    result: str,
    metadata: Optional[Dict[str, Any]] = None,
    db_session = None
):
    """
    Records an immutable audit event for security and compliance.
    Saves to database if session provided, and emits structured log.
    """
    clean_meta = sanitize_metadata(metadata)
    event_id = str(uuid.uuid4())
    event_payload = {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor_id": str(actor_id) if actor_id else "anonymous",
        "action": action,
        "resource": resource,
        "result": result,
        "metadata": clean_meta
    }

    audit_logger.info("AUDIT_EVENT: %s", json.dumps(event_payload))

    if db_session:
        try:
            # We import dynamically to avoid circular dependencies with database models
            from backend.database.models import AuditEvent
            db_event = AuditEvent(
                id=event_id,
                actor_id=str(actor_id) if actor_id else "anonymous",
                action=action,
                resource=resource,
                result=result,
                metadata_json=json.dumps(clean_meta),
                created_at=datetime.now(timezone.utc)
            )
            db_session.add(db_event)
            db_session.commit()
        except Exception as exc:
            audit_logger.error("Failed to commit audit event to database: %s", exc)

def log_security_event(
    event_type: str,
    severity: str,
    ip_address: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    db_session = None
):
    """
    Records security-specific occurrences (login failure, rate-limit trigger, blocked payment).
    """
    clean_details = sanitize_metadata(details)
    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "severity": severity,
        "ip_address": ip_address or "unknown",
        "user_id": str(user_id) if user_id else "anonymous",
        "details": clean_details
    }
    audit_logger.warning("SECURITY_EVENT: %s", json.dumps(payload))

    if db_session:
        try:
            from backend.database.models import SecurityEvent
            sec_event = SecurityEvent(
                id=event_id,
                event_type=event_type,
                severity=severity,
                ip_address=ip_address or "unknown",
                user_id=str(user_id) if user_id else None,
                details_json=json.dumps(clean_details),
                created_at=datetime.now(timezone.utc)
            )
            db_session.add(sec_event)
            db_session.commit()
        except Exception as exc:
            audit_logger.error("Failed to commit security event to database: %s", exc)
