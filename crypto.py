"""Fernet encryption/decryption for sensitive database fields."""

import os
import base64
from pathlib import Path
from cryptography.fernet import Fernet

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        key_path = Path(os.environ.get("DATA_DIR", "/app/data")) / ".secret_key"
        if key_path.exists():
            secret_key = key_path.read_text().strip()
        else:
            secret_key = Fernet.generate_key().decode()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(secret_key)

    # Ensure the key is valid Fernet format (url-safe base64, 32 bytes)
    try:
        _fernet = Fernet(secret_key.encode() if isinstance(secret_key, str) else secret_key)
    except Exception:
        # If raw key provided, derive a valid Fernet key from it
        raw = secret_key.encode() if isinstance(secret_key, str) else secret_key
        padded = raw.ljust(32, b"\0")[:32]
        key = base64.urlsafe_b64encode(padded)
        _fernet = Fernet(key)

    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string, returning a base64 Fernet token."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
