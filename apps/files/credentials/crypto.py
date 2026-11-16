from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.result import OperationResult


@dataclass(frozen=True, slots=True)
class KdfConfig:
    name: str = "argon2id"
    time_cost: int = 3
    memory_cost: int = 65536
    parallelism: int = 2
    hash_len: int = 32

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "time_cost": self.time_cost,
            "memory_cost": self.memory_cost,
            "parallelism": self.parallelism,
            "hash_len": self.hash_len,
        }

    @classmethod
    def from_dict(cls, value: dict | None) -> "KdfConfig":
        data = dict(value or {})
        return cls(
            name=str(data.get("name") or "argon2id"),
            time_cost=int(data.get("time_cost", 3)),
            memory_cost=int(data.get("memory_cost", 65536)),
            parallelism=int(data.get("parallelism", 2)),
            hash_len=int(data.get("hash_len", 32)),
        )


def b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def new_salt() -> bytes:
    return os.urandom(16)


def derive_key(password: str, salt: bytes, config: KdfConfig | None = None) -> bytes:
    cfg = config or KdfConfig()
    if cfg.name != "argon2id":
        raise ValueError(f"Unsupported KDF: {cfg.name}")
    return hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=cfg.time_cost,
        memory_cost=cfg.memory_cost,
        parallelism=cfg.parallelism,
        hash_len=cfg.hash_len,
        type=Type.ID,
    )


def encrypt_text(key: bytes, value: str, *, aad: str = "") -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), aad.encode("utf-8"))
    return json.dumps(
        {
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": b64encode(nonce),
            "ciphertext": b64encode(ciphertext),
        },
        separators=(",", ":"),
    )


def decrypt_text(key: bytes, payload: str | None, *, aad: str = "") -> OperationResult:
    if not payload:
        return OperationResult.success("No encrypted value.", data="")
    try:
        data = json.loads(payload)
        nonce = b64decode(str(data["nonce"]))
        ciphertext = b64decode(str(data["ciphertext"]))
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8"))
        return OperationResult.success("Encrypted value decrypted.", data=plaintext.decode("utf-8"))
    except (InvalidTag, ValueError, KeyError, json.JSONDecodeError) as exc:
        return OperationResult.failure(
            "Could not decrypt credential value.",
            technical_details=f"{type(exc).__name__}: encrypted data is invalid or the password is wrong.",
        )


def encrypt_json(key: bytes, value: dict, *, aad: str = "") -> str:
    return encrypt_text(key, json.dumps(value, separators=(",", ":"), sort_keys=True), aad=aad)


def decrypt_json(key: bytes, payload: str, *, aad: str = "") -> OperationResult:
    decrypted = decrypt_text(key, payload, aad=aad)
    if not decrypted.ok:
        return decrypted
    try:
        return OperationResult.success("Encrypted JSON decrypted.", data=json.loads(decrypted.data))
    except json.JSONDecodeError as exc:
        return OperationResult.failure(
            "Could not decode encrypted JSON.",
            technical_details=f"{type(exc).__name__}: {exc}",
        )
