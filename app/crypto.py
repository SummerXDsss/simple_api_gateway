"""
轻量本地加密模块 — 无第三方依赖。

算法：PBKDF2-HMAC-SHA256 派生密钥 + ChaCha20 风格的 XOR 密钥流（基于 SHA-256 链式扩展）。
密钥来源：本机 MAC 地址（uuid.getnode()），无需用户输入。
存储格式：enc:<base64url(salt[16] + ciphertext)>

安全说明：对于本地配置文件防止直接明文读取，安全性足够。
          不适用于高安全传输场景。
"""
from __future__ import annotations

import base64
import hashlib
import os
import uuid


_SALT_LEN = 16
_ITER = 100_000
_PREFIX = "enc:"


def _machine_secret() -> bytes:
    """从本机 MAC 地址派生一个稳定的机器唯一标识。"""
    node = uuid.getnode()
    return node.to_bytes(6, "big") + b"local-ai-gateway-v1"


def _derive_key(salt: bytes, length: int = 32) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        _machine_secret(),
        salt,
        _ITER,
        dklen=length,
    )


def _xor_keystream(data: bytes, key: bytes) -> bytes:
    """用 SHA-256 链式扩展生成与 data 等长的密钥流，然后 XOR。"""
    stream = bytearray()
    block = key
    while len(stream) < len(data):
        block = hashlib.sha256(block).digest()
        stream.extend(block)
    return bytes(a ^ b for a, b in zip(data, stream))


def encrypt(plaintext: str) -> str:
    """加密字符串，返回 enc:<base64url> 格式。"""
    if not plaintext:
        return plaintext
    salt = os.urandom(_SALT_LEN)
    key = _derive_key(salt)
    ct = _xor_keystream(plaintext.encode("utf-8"), key)
    payload = base64.urlsafe_b64encode(salt + ct).decode("ascii")
    return f"{_PREFIX}{payload}"


def decrypt(value: str) -> str:
    """解密 enc:<base64url> 格式字符串，失败时返回空串。"""
    if not value.startswith(_PREFIX):
        return value  # 兼容旧明文
    try:
        raw = base64.urlsafe_b64decode(value[len(_PREFIX):])
        salt, ct = raw[:_SALT_LEN], raw[_SALT_LEN:]
        key = _derive_key(salt)
        return _xor_keystream(ct, key).decode("utf-8")
    except Exception:
        return ""


def is_encrypted(value: str) -> bool:
    return value.startswith(_PREFIX)
