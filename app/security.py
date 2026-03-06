from __future__ import annotations

import hashlib
import secrets
from hmac import compare_digest

from .schemas import LocalKeyRecord


def hash_key(plain_key: str) -> str:
    return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()


def generate_local_api_key() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(24)
    plain_key = f"lak-{token}"
    return plain_key, hash_key(plain_key), plain_key[:12]


def verify_local_api_key(
    plain_key: str, records: list[LocalKeyRecord]
) -> LocalKeyRecord | None:
    target_hash = hash_key(plain_key)
    for record in records:
        if record.enabled and compare_digest(record.key_hash, target_hash):
            return record
    return None
