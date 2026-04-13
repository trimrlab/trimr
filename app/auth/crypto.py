"""
@Project: Trimr
@File: app/auth/crypto.py
@Description: Encryption and decryption utilities
"""

import base64
import hashlib
import json
import os
from typing import Optional


def derive_key(password: str, salt: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt,
        iterations=100000,
        dklen=32,
    )

def encrypt(data: dict, password: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    nonce = os.urandom(12)

    key = derive_key(password, salt)

    aesgcm = AESGCM(key)
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    combined = salt + nonce + ciphertext

    return base64.b64encode(combined).decode("utf-8")

def decrypt(encrypted_b64: str, password: str) -> Optional[dict]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        combined = base64.b64decode(encrypted_b64)

        salt = combined[:16]
        nonce = combined[16:28]
        ciphertext = combined[28:]

        key = derive_key(password, salt)

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return json.loads(plaintext.decode("utf-8"))

    except Exception as e:
        return None

def encrypt_with_token(data: dict, device_token: str) -> str:
    return encrypt(data, device_token[:32])

def decrypt_with_token(encrypted_b64: str, device_token: str) -> Optional[dict]:
    return decrypt(encrypted_b64, device_token[:32])
