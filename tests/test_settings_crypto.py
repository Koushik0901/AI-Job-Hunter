import pytest


@pytest.fixture(autouse=True)
def reset_crypto():
    """Reset module-level cache between tests."""
    import ai_job_hunter.settings_crypto as sc
    sc._fernet = None
    sc._WARNED = False
    yield
    sc._fernet = None
    sc._WARNED = False


def test_encrypt_decrypt_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)

    import ai_job_hunter.settings_crypto as sc
    plaintext = "sk-or-v1-supersecretkey"
    encrypted = sc.encrypt(plaintext)
    assert encrypted != plaintext
    assert sc.decrypt(encrypted) == plaintext


def test_encrypt_decrypt_different_values(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)

    import ai_job_hunter.settings_crypto as sc
    assert sc.encrypt("value-a") != sc.encrypt("value-b")


def test_passthrough_without_key(monkeypatch):
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)

    import ai_job_hunter.settings_crypto as sc
    plaintext = "my-secret"
    assert sc.encrypt(plaintext) == plaintext
    assert sc.decrypt(plaintext) == plaintext


def test_encrypt_passthrough_with_invalid_key(monkeypatch):
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    import ai_job_hunter.settings_crypto as sc
    plaintext = "my-secret"
    assert sc.encrypt(plaintext) == plaintext
    assert sc.decrypt(plaintext) == plaintext


def test_decrypt_graceful_on_non_fernet_value(monkeypatch):
    """If a value was stored as plaintext (no encryption key at write time),
    decrypt() should return it as-is even when a key is now configured."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)

    import ai_job_hunter.settings_crypto as sc
    # "plaintext" is not valid Fernet ciphertext; should come back unchanged
    assert sc.decrypt("plaintext-stored-before-encryption") == "plaintext-stored-before-encryption"


def test_mask_long_value():
    import ai_job_hunter.settings_crypto as sc
    assert sc.mask("sk-or-v1-abcdef1234") == "sk-o****1234"


def test_mask_exactly_8_chars():
    import ai_job_hunter.settings_crypto as sc
    assert sc.mask("12345678") == "****"


def test_mask_short_value():
    import ai_job_hunter.settings_crypto as sc
    assert sc.mask("abc") == "****"


def test_mask_empty():
    import ai_job_hunter.settings_crypto as sc
    assert sc.mask("") == ""
