"""PII encryption at rest. Requires ENCRYPTION_KEY (32-byte hex)."""
import os
from base64 import b64encode, b64decode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _get_fernet(key_hex: str | None) -> Fernet | None:
    if not key_hex or len(key_hex) < 64:
        return None
    try:
        key_bytes = bytes.fromhex(key_hex[:64])
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"taxai_pii", iterations=100000)
        key = b64encode(kdf.derive(key_bytes))
        return Fernet(key)
    except Exception:
        return None


def encrypt_pii(plain: str, encryption_key: str | None) -> str:
    if not encryption_key or not plain:
        return plain
    f = _get_fernet(encryption_key)
    if not f:
        return plain
    try:
        return f.encrypt(plain.encode()).decode()
    except Exception:
        return plain


def decrypt_pii(cipher: str, encryption_key: str | None) -> str:
    if not encryption_key or not cipher:
        return cipher
    f = _get_fernet(encryption_key)
    if not f:
        return cipher
    try:
        return f.decrypt(cipher.encode()).decode()
    except Exception:
        return cipher
