"""Integration credential encryption (PROMPT-018 §6/§31).

`integration_configuration.credentials_encrypted` must never hold
plaintext. This module wraps `cryptography.fernet.Fernet` (already an
available dependency in this codebase) — symmetric, authenticated
encryption, sufficient for "encrypt a small JSON blob at rest" without
inventing a bespoke scheme.

Key management is an explicit Open Decision (§43 #11) — no key-rotation/
KMS strategy is approved. `settings.gst_integration_credential_key` lets
an operator supply a real key; when unset (dev/test convenience only) a
key is deterministically derived from `jwt_secret_key` so local
environments work without extra setup. Production deployments SHOULD set
an independent key — this fallback is documented, not silently relied on.
"""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.gst_integration_credential_key:
        key = settings.gst_integration_credential_key.encode("utf-8")
    else:
        # Deterministic dev/test-only fallback — derives a valid 32-byte
        # urlsafe-base64 Fernet key from the existing JWT secret so this
        # never needs its own .env entry in development. NOT a substitute
        # for a real key-management decision in production.
        digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_credentials(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True).encode("utf-8")
    return _fernet().encrypt(payload).decode("utf-8")


def decrypt_credentials(token: str) -> dict[str, Any]:
    try:
        payload = _fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Stored integration credentials could not be decrypted.") from exc
    return json.loads(payload.decode("utf-8"))
