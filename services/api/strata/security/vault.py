"""Encrypted dataset storage: encrypt -> store blob -> keep wrapped key apart; shred on delete.

Backends for the ciphertext blob:
* `db`       - bytea column on `datasets` (default; simplest, works on SQLite).
* `local`    - files under STRATA_STORAGE_DIR (single-node deployments).
* `supabase` - private Supabase Storage bucket (see supabase/migrations/0003_storage.sql).
Ciphertext is useless without the wrapped data key in `dataset_keys`.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from strata.db.models import Dataset, DatasetKey
from strata.security.crypto import Keyring, decrypt_payload, encrypt_payload


class BlobStore(Protocol):
    def put(self, path: str, data: bytes) -> None: ...
    def get(self, path: str) -> bytes: ...
    def delete(self, path: str) -> None: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _p(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("path escapes storage root")
        return p

    def put(self, path: str, data: bytes) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        tmp.replace(p)

    def get(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def delete(self, path: str) -> None:
        self._p(path).unlink(missing_ok=True)


class SupabaseBlobStore:
    """Supabase Storage REST API using the service-role key (server side only)."""

    def __init__(self, url: str, service_key: str, bucket: str) -> None:
        self.base = url.rstrip("/") + "/storage/v1/object"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def put(self, path: str, data: bytes) -> None:
        r = httpx.post(
            f"{self.base}/{self.bucket}/{path}",
            content=data,
            headers={**self.headers, "Content-Type": "application/octet-stream",
                     "x-upsert": "true"},
            timeout=60,
        )
        r.raise_for_status()

    def get(self, path: str) -> bytes:
        r = httpx.get(f"{self.base}/authenticated/{self.bucket}/{path}", headers=self.headers,
                      timeout=60)
        r.raise_for_status()
        return r.content

    def delete(self, path: str) -> None:
        r = httpx.request("DELETE", f"{self.base}/{self.bucket}", json={"prefixes": [path]},
                          headers=self.headers, timeout=30)
        if r.status_code not in (200, 404):
            r.raise_for_status()


def blob_store_from_settings() -> BlobStore | None:
    from strata.config import get_settings

    s = get_settings()
    if s.storage_backend == "local":
        return LocalBlobStore(s.storage_dir)
    if s.storage_backend == "supabase":
        if not (s.supabase_url and s.supabase_service_role_key):
            raise RuntimeError("supabase storage needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseBlobStore(s.supabase_url, s.supabase_service_role_key, s.storage_bucket)
    return None


class DatasetShreddedError(Exception):
    """The dataset's data key was destroyed; its payload is unrecoverable."""


class DatasetVault:
    def __init__(self, keyring: Keyring, blobs: BlobStore | None = None) -> None:
        self.keyring = keyring
        self.blobs = blobs

    def seal(self, session: Session, dataset: Dataset, plaintext: bytes) -> None:
        """Encrypt `plaintext` into `dataset` (which must already have id and owner_id)."""
        if dataset.id is None:
            dataset.id = uuid.uuid4()
        enc = encrypt_payload(
            plaintext, dataset_id=str(dataset.id), owner_id=str(dataset.owner_id),
            keyring=self.keyring,
        )
        dataset.payload_sha256 = hashlib.sha256(plaintext).hexdigest()
        dataset.nonce = enc.nonce
        if self.blobs is None:
            dataset.ciphertext = enc.ciphertext
            dataset.storage_path = None
        else:
            path = f"{dataset.owner_id}/{dataset.id}.bin"
            self.blobs.put(path, enc.ciphertext)
            dataset.ciphertext = None
            dataset.storage_path = path
        dataset.key = DatasetKey(
            dataset_id=dataset.id, owner_id=dataset.owner_id,
            wrapped_key=enc.wrapped_key, kek_id=enc.kek_id,
        )
        session.add(dataset)

    def open(self, session: Session, dataset: Dataset) -> bytes:
        key = session.get(DatasetKey, dataset.id)
        if key is None:
            raise DatasetShreddedError(str(dataset.id))
        if dataset.ciphertext is not None:
            ct = dataset.ciphertext
        elif dataset.storage_path and self.blobs is not None:
            ct = self.blobs.get(dataset.storage_path)
        else:
            raise DatasetShreddedError(str(dataset.id))
        pt = decrypt_payload(
            ct, dataset.nonce, key.wrapped_key, key.kek_id,
            dataset_id=str(dataset.id), owner_id=str(dataset.owner_id), keyring=self.keyring,
        )
        if hashlib.sha256(pt).hexdigest() != dataset.payload_sha256:
            raise DatasetShreddedError("payload hash mismatch")
        return pt

    def shred(self, session: Session, dataset: Dataset) -> None:
        """Destroy the data key first (crypto-shred), then the ciphertext, then the row."""
        key = session.get(DatasetKey, dataset.id)
        if key is not None:
            key.wrapped_key = b"\x00" * len(key.wrapped_key)
            session.flush()
            session.delete(key)
            session.flush()
        if dataset.storage_path and self.blobs is not None:
            self.blobs.delete(dataset.storage_path)
        session.delete(dataset)
        session.flush()


def vault_from_settings() -> DatasetVault:
    from strata.security.crypto import keyring_from_settings

    return DatasetVault(keyring_from_settings(), blob_store_from_settings())
