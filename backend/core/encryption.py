import os
import base64
import hmac
import hashlib
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

DEFAULT_DEV_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
DEFAULT_DEV_HMAC_KEY = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"

class EncryptionService:
    """
    Application-level AES-256-GCM encryption and HMAC-SHA-256 blind index service.
    Follows zero-plaintext storage policy for sensitive PII.
    Supports key versioning for safe key rotation.
    """

    def __init__(self, key_hex: Optional[str] = None, hmac_key_hex: Optional[str] = None, key_version: str = "v1"):
        raw_key_hex = key_hex or os.getenv("YOGII_ENCRYPTION_KEY", DEFAULT_DEV_KEY)
        raw_hmac_hex = hmac_key_hex or os.getenv("YOGII_LOOKUP_HMAC_KEY", DEFAULT_DEV_HMAC_KEY)

        try:
            self._key = bytes.fromhex(raw_key_hex)
        except Exception:
            self._key = hashlib.sha256(raw_key_hex.encode()).digest()

        if len(self._key) != 32:
            raise ValueError(f"AES-256 key must be 32 bytes, got {len(self._key)}")

        try:
            self._hmac_key = bytes.fromhex(raw_hmac_hex)
        except Exception:
            self._hmac_key = hashlib.sha256(raw_hmac_hex.encode()).digest()

        self.key_version = key_version or os.getenv("YOGII_KEY_VERSION", "v1")
        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypts plaintext string using AES-256-GCM with a fresh 96-bit (12-byte) nonce.
        Format returned: {key_version}${nonce_b64}${ciphertext_and_tag_b64}
        """
        if plaintext is None:
            return None
        if not isinstance(plaintext, str):
            plaintext = str(plaintext)

        nonce = os.urandom(12)  # 96-bit standard nonce for GCM
        ciphertext_with_tag = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

        nonce_b64 = base64.b64encode(nonce).decode("ascii")
        ct_b64 = base64.b64encode(ciphertext_with_tag).decode("ascii")
        return f"{self.key_version}${nonce_b64}${ct_b64}"

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypts an encrypted token formatted as {key_version}${nonce_b64}${ciphertext_and_tag_b64}.
        """
        if not encrypted_token:
            return ""

        parts = encrypted_token.split("$")
        if len(parts) != 3:
            raise ValueError("Invalid encrypted token format")

        version, nonce_b64, ct_b64 = parts
        nonce = base64.b64decode(nonce_b64.encode("ascii"))
        ciphertext_with_tag = base64.b64decode(ct_b64.encode("ascii"))

        decrypted_bytes = self._aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return decrypted_bytes.decode("utf-8")

    def blind_index(self, value: str) -> str:
        """
        Calculates a cryptographically salted HMAC-SHA-256 blind index for searchable equality lookup.
        The input value is normalized (trimmed, lowercased).
        Never uses unsalted SHA256 of low-entropy inputs like phone numbers.
        """
        if value is None:
            return ""
        normalized = str(value).strip().lower()
        return hmac.new(self._hmac_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


# Password Hashing using Argon2id
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # 19 MiB
    parallelism=1,
    hash_len=32,
    type=Type.ID
)

def hash_password(password: str) -> str:
    """Hashes a password securely using Argon2id."""
    return _ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a password against an Argon2id hash."""
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, Exception):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True when the stored hash uses older Argon2id parameters."""
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        return False


# Precomputed hash used to spend equal time on unknown accounts at login.
DUMMY_PASSWORD_HASH = _ph.hash("not-a-real-password-used-for-timing-only")

# Global singleton encryption service, keyed from server configuration
from backend.core.config import settings as _settings  # noqa: E402

encryption_service = EncryptionService(
    _settings.YOGII_ENCRYPTION_KEY, _settings.YOGII_LOOKUP_HMAC_KEY, _settings.YOGII_KEY_VERSION
)
