"""AES-256-GCM envelope encryption for dataset payloads.

* A random 256-bit data encryption key (DEK) is generated per dataset.
* The payload is encrypted with the DEK (AES-256-GCM, 96-bit random nonce). The associated
  data binds the ciphertext to its dataset id and owner, so ciphertexts cannot be swapped
  between rows.
* The DEK is wrapped with the key-encryption key (KEK, `STRATA_DATA_KEY`) using AES-256-GCM
  and stored in `dataset_keys`, apart from the ciphertext.
* Deleting the wrapped DEK ("crypto-shredding") makes every copy of the ciphertext,
  including copies in backups or object storage, permanently undecryptable.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
KEY_LEN = 32
WRAP_VERSION = b"\x01"


class DecryptionError(Exception):
    """Ciphertext or key failed authentication (tampered, wrong key, or shredded)."""


def kek_id(kek: bytes) -> str:
    """Stable, non-secret identifier of a KEK (used to pick the key during rotation)."""
    return hashlib.sha256(b"strata-kek-id:" + kek).hexdigest()[:16]


@dataclass(frozen=True)
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    wrapped_key: bytes
    kek_id: str


class Keyring:
    """Primary KEK used for wrapping plus previous KEKs accepted for unwrapping."""

    def __init__(self, primary: bytes, previous: list[bytes] | None = None) -> None:
        for k in [primary, *(previous or [])]:
            if len(k) != KEY_LEN:
                raise ValueError("KEKs must be 32 bytes")
        self._primary = primary
        self._keys = {kek_id(k): k for k in [primary, *(previous or [])]}

    @property
    def primary_id(self) -> str:
        return kek_id(self._primary)

    def wrap(self, dek: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(NONCE_LEN)
        return WRAP_VERSION + nonce + AESGCM(self._primary).encrypt(nonce, dek, aad)

    def unwrap(self, wrapped: bytes, key_id: str, aad: bytes) -> bytes:
        kek = self._keys.get(key_id)
        if kek is None:
            raise DecryptionError(f"unknown key-encryption key id {key_id}")
        if not wrapped or wrapped[:1] != WRAP_VERSION:
            raise DecryptionError("unsupported wrapped-key format")
        nonce, body = wrapped[1 : 1 + NONCE_LEN], wrapped[1 + NONCE_LEN :]
        try:
            return AESGCM(kek).decrypt(nonce, body, aad)
        except InvalidTag as exc:
            raise DecryptionError("data key failed authentication") from exc

    def rewrap(self, wrapped: bytes, key_id: str, aad: bytes) -> tuple[bytes, str]:
        """Re-wrap a DEK under the current primary KEK (key rotation)."""
        return self.wrap(self.unwrap(wrapped, key_id, aad), aad), self.primary_id


def _aad(dataset_id: str, owner_id: str, purpose: bytes) -> bytes:
    return b"strata/v1/" + purpose + b"/" + dataset_id.encode() + b"/" + owner_id.encode()


def encrypt_payload(
    plaintext: bytes, *, dataset_id: str, owner_id: str, keyring: Keyring
) -> EncryptedPayload:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(dek).encrypt(nonce, plaintext, _aad(dataset_id, owner_id, b"payload"))
    wrapped = keyring.wrap(dek, _aad(dataset_id, owner_id, b"dek"))
    return EncryptedPayload(ct, nonce, wrapped, keyring.primary_id)


def decrypt_payload(
    ciphertext: bytes,
    nonce: bytes,
    wrapped_key: bytes,
    key_id: str,
    *,
    dataset_id: str,
    owner_id: str,
    keyring: Keyring,
) -> bytes:
    dek = keyring.unwrap(wrapped_key, key_id, _aad(dataset_id, owner_id, b"dek"))
    try:
        return AESGCM(dek).decrypt(nonce, ciphertext, _aad(dataset_id, owner_id, b"payload"))
    except InvalidTag as exc:
        raise DecryptionError("payload failed authentication") from exc


def keyring_from_settings() -> Keyring:
    from strata.config import get_settings

    s = get_settings()
    return Keyring(s.kek_bytes(), s.previous_keks())
