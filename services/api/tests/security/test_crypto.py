from __future__ import annotations

import os
import uuid

import pytest

from strata.security.crypto import (
    DecryptionError,
    Keyring,
    decrypt_payload,
    encrypt_payload,
    kek_id,
)


def _kr(prev: list[bytes] | None = None) -> Keyring:
    return Keyring(os.urandom(32), prev)


def test_round_trip_and_binding():
    kr = _kr()
    ds, owner = str(uuid.uuid4()), str(uuid.uuid4())
    pt = os.urandom(10_000)
    enc = encrypt_payload(pt, dataset_id=ds, owner_id=owner, keyring=kr)
    assert enc.ciphertext != pt and len(enc.nonce) == 12 and enc.kek_id == kr.primary_id
    out = decrypt_payload(
        enc.ciphertext,
        enc.nonce,
        enc.wrapped_key,
        enc.kek_id,
        dataset_id=ds,
        owner_id=owner,
        keyring=kr,
    )
    assert out == pt
    # Ciphertext is bound to its dataset id and owner (AAD).
    for d, o in ((str(uuid.uuid4()), owner), (ds, str(uuid.uuid4()))):
        with pytest.raises(DecryptionError):
            decrypt_payload(
                enc.ciphertext,
                enc.nonce,
                enc.wrapped_key,
                enc.kek_id,
                dataset_id=d,
                owner_id=o,
                keyring=kr,
            )


def test_tamper_and_wrong_key_detected():
    kr = _kr()
    enc = encrypt_payload(b"secret", dataset_id="d", owner_id="o", keyring=kr)
    bad = bytearray(enc.ciphertext)
    bad[0] ^= 1
    with pytest.raises(DecryptionError):
        decrypt_payload(
            bytes(bad),
            enc.nonce,
            enc.wrapped_key,
            enc.kek_id,
            dataset_id="d",
            owner_id="o",
            keyring=kr,
        )
    with pytest.raises(DecryptionError):
        decrypt_payload(
            enc.ciphertext,
            enc.nonce,
            enc.wrapped_key,
            enc.kek_id,
            dataset_id="d",
            owner_id="o",
            keyring=_kr(),
        )
    # Shredded (zeroed) wrapped key cannot be unwrapped.
    with pytest.raises(DecryptionError):
        decrypt_payload(
            enc.ciphertext,
            enc.nonce,
            b"\x00" * len(enc.wrapped_key),
            enc.kek_id,
            dataset_id="d",
            owner_id="o",
            keyring=kr,
        )


def test_unique_data_keys_and_nonces():
    kr = _kr()
    a = encrypt_payload(b"same", dataset_id="d", owner_id="o", keyring=kr)
    b = encrypt_payload(b"same", dataset_id="d", owner_id="o", keyring=kr)
    assert a.ciphertext != b.ciphertext and a.wrapped_key != b.wrapped_key


def test_key_rotation():
    old = os.urandom(32)
    enc = encrypt_payload(b"x", dataset_id="d", owner_id="o", keyring=Keyring(old))
    new = Keyring(os.urandom(32), [old])
    assert (
        decrypt_payload(
            enc.ciphertext,
            enc.nonce,
            enc.wrapped_key,
            enc.kek_id,
            dataset_id="d",
            owner_id="o",
            keyring=new,
        )
        == b"x"
    )
    from strata.security.crypto import _aad

    wrapped, kid = new.rewrap(enc.wrapped_key, enc.kek_id, _aad("d", "o", b"dek"))
    assert kid == new.primary_id != kek_id(old)
    assert (
        decrypt_payload(
            enc.ciphertext,
            enc.nonce,
            wrapped,
            kid,
            dataset_id="d",
            owner_id="o",
            keyring=Keyring(new._primary),
        )
        == b"x"
    )


def test_rejects_bad_key_length():
    with pytest.raises(ValueError):
        Keyring(b"short")
