import pytest
from backend.core.encryption import EncryptionService, hash_password, verify_password

def test_aes_gcm_encryption_roundtrip():
    service = EncryptionService()
    plaintext = "Yogesh Kumar Sensitive PII 9876543210"
    token = service.encrypt(plaintext)

    assert token != plaintext
    assert token.startswith("v1$")
    parts = token.split("$")
    assert len(parts) == 3

    decrypted = service.decrypt(token)
    assert decrypted == plaintext

def test_nonce_freshness_produces_distinct_ciphertexts():
    service = EncryptionService()
    plaintext = "Identical Data"
    token1 = service.encrypt(plaintext)
    token2 = service.encrypt(plaintext)

    assert token1 != token2
    assert service.decrypt(token1) == plaintext
    assert service.decrypt(token2) == plaintext

def test_tampered_ciphertext_fails_decryption():
    service = EncryptionService()
    token = service.encrypt("Legitimate message")
    parts = token.split("$")
    # Corrupt the ciphertext payload
    corrupted = f"{parts[0]}${parts[1]}$corruptedpayload"
    with pytest.raises(Exception):
        service.decrypt(corrupted)

def test_blind_index_normalization_and_determinism():
    service = EncryptionService()
    val1 = "Yogesh@Yogii"
    val2 = "  yogesh@yogii  "
    
    hash1 = service.blind_index(val1)
    hash2 = service.blind_index(val2)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest length
    # Salting invariant: blind index must not equal unsalted sha256
    import hashlib
    unsalted = hashlib.sha256("yogesh@yogii".encode()).hexdigest()
    assert hash1 != unsalted

def test_argon2id_password_hashing():
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed.startswith("$argon2id$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
