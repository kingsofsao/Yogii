"""Normalisation and validation of user-supplied identifiers.

Every identifier is normalised before it is hashed for lookup, so that
"Rahul@UPI " and "rahul@upi" find the same record.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from email_validator import EmailNotValidError, validate_email

UPI_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}@[a-z][a-z0-9]{1,31}$")
PHONE_RE = re.compile(r"^[6-9][0-9]{9}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,79}$")

# Keys that must never be accepted in any request body.
FORBIDDEN_SECRET_FIELDS = frozenset({
    "pin", "upi_pin", "mpin", "otp", "cvv", "cvc", "card_number", "card_pin",
    "bank_password", "netbanking_password", "atm_pin",
})


class InvalidInput(ValueError):
    pass


def normalize_upi_id(value: str) -> str:
    v = (value or "").strip().lower()
    if not UPI_ID_RE.match(v):
        raise InvalidInput("Enter a valid UPI ID, for example name@bank.")
    return v


def normalize_phone(value: str) -> str:
    digits = re.sub(r"[\s-]", "", (value or "").strip())
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not PHONE_RE.match(digits):
        raise InvalidInput("Enter a 10-digit Indian mobile number.")
    return digits


def normalize_email(value: str) -> str:
    try:
        return validate_email((value or "").strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise InvalidInput("Enter a valid email address.")


def normalize_name(value: str) -> str:
    v = re.sub(r"\s+", " ", (value or "").strip())
    if not NAME_RE.match(v):
        raise InvalidInput("Enter your name using letters, spaces, apostrophes or hyphens.")
    return v


def check_password_strength(password: str) -> str:
    if len(password) < 10 or len(password) > 128:
        raise InvalidInput("Password must be 10 to 128 characters long.")
    if not (re.search(r"[a-z]", password) and re.search(r"[A-Z]", password) and re.search(r"[0-9]", password)):
        raise InvalidInput("Password must include uppercase and lowercase letters and a number.")
    return password


def normalize_recipient_query(value: str) -> tuple[str, str]:
    """Return ("upi" | "phone", normalised value) for a recipient search."""
    v = (value or "").strip()
    if "@" in v:
        return "upi", normalize_upi_id(v)
    return "phone", normalize_phone(v)


def to_money(value) -> Decimal:
    """Parse an amount into rupees with two decimal places."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InvalidInput("Enter a valid amount.")
    if not d.is_finite() or d <= 0:
        raise InvalidInput("Amount must be greater than zero.")
    if d != d.quantize(Decimal("0.01")):
        raise InvalidInput("Amount can have at most two decimal places.")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def contains_forbidden_secret(payload) -> str | None:
    """Return the first forbidden key found anywhere in a JSON-like payload."""
    if isinstance(payload, dict):
        for key, val in payload.items():
            if str(key).lower() in FORBIDDEN_SECRET_FIELDS:
                return str(key)
            found = contains_forbidden_secret(val)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = contains_forbidden_secret(item)
            if found:
                return found
    return None
