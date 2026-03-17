"""Symmetric Fernet encryption for API keys stored at rest.

Reads ``API_KEY_ENCRYPTION_SECRET`` from the environment.  When the variable
is absent or empty, encryption is a transparent no-op so development isn't
blocked.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

log = logging.getLogger(__name__)

_secret = os.getenv("API_KEY_ENCRYPTION_SECRET", "")

_fernet = None
if _secret:
    try:
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(_secret.encode()).digest())
        _fernet = Fernet(key)
    except ImportError:
        log.warning("cryptography package not installed — API keys stored unencrypted")


def encrypt(plaintext: str) -> str:
    if _fernet is None:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if _fernet is None:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def mask(value: str) -> str:
    """Show only the last 4 characters, masking the rest."""
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]
