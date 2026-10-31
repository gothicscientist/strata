"""Dataset ingestion and decryption (service layer used by routers and job handlers).

Stored payload formats (always AES-256-GCM encrypted at rest):
* ``g25-json-v1``   - names + coordinate matrix of an uploaded G25-style sheet.
* ``dosage-npz-v1`` - raw DNA harmonised to the reference SNP panel: int8 dosage of the
                      panel's counted allele (-1 missing). Raw calls are discarded.
* ``calls-npz-v1``  - only when no reference panel is installed: biallelic SNV calls
                      (rsid/chrom/pos/alleles) so the dataset can be harmonised once the panel
                      exists. Indels, no-calls and vendor metadata are not kept.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from strata.api import science
from strata.api.errors import ApiError
from strata.db.models import Dataset
from strata.security.auth import Principal
from strata.security.uploads import sanitize_filename
from strata.security.vault import DatasetVault

G25_SPACE = "g25"


@dataclass
class DatasetPayload:
    format: str
    meta: dict[str, Any]
    arrays: dict[str, np.ndarray]


# ------------------------------------------------------------------ codec


def _encode(payload: DatasetPayload) -> bytes:
    if payload.format == "g25-json-v1":
        body = {
            "format": payload.format,
            **payload.meta,
            "matrix": payload.arrays["matrix"].tolist(),
        }
        return json.dumps(body, separators=(",", ":")).encode()
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        __meta__=np.frombuffer(
            json.dumps({"format": payload.format, **payload.meta}).encode(), dtype=np.uint8
        ),
        **payload.arrays,
    )
    return buf.getvalue()


def decode_payload(raw: bytes) -> DatasetPayload:
    if raw[:1] == b"{":
        body = json.loads(raw)
        fmt = body.pop("format")
        matrix = np.asarray(body.pop("matrix"), dtype=np.float64)
        return DatasetPayload(fmt, body, {"matrix": matrix})
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        meta = json.loads(z["__meta__"].tobytes())
        arrays = {k: z[k] for k in z.files if k != "__meta__"}
    return DatasetPayload(meta.pop("format"), meta, arrays)


# ------------------------------------------------------------------ ingestion


def _warning_strings(ws: list[Any]) -> list[str]:
    out = []
    for w in ws or []:
        if isinstance(w, dict):
            out.append(w.get("message") or w.get("code") or str(w))
        elif hasattr(w, "message"):
            out.append(str(w.message))
        else:
            out.append(str(w))
    return out


def _ingest_g25(text: str) -> tuple[DatasetPayload, dict[str, Any], dict[str, Any]]:
    io_mod = science._module("strata.io")
    table = io_mod.parse_g25(text)
    matrix = np.asarray(table.matrix, dtype=np.float64)
    warnings = [w.model_dump() for w in table.warnings]
    qc = {
        "n_samples": len(table.names),
        "n_dims": int(table.n_dims),
        "scaled": table.scaled,
        "n_variants": 0,
        "warnings": _warning_strings(warnings),
        "warning_details": warnings,
    }
    summary = {
        "space": G25_SPACE,
        "sample_names": list(table.names),
        "n_samples": len(table.names),
        "n_dims": int(table.n_dims),
        "scaled": table.scaled,
    }
    payload = DatasetPayload(
        "g25-json-v1",
        {"space": G25_SPACE, "names": list(table.names), "scaled": table.scaled},
        {"matrix": matrix},
    )
    return payload, qc, summary


def _ingest_raw(
    data: bytes, filename: str, sample_name: str
) -> tuple[DatasetPayload, dict[str, Any], dict[str, Any], str | None]:
    io_mod = science._module("strata.io")
    raw = io_mod.parse_raw_dna(data, filename)
    qc_model = raw.qc
    qc: dict[str, Any] = qc_model.model_dump(mode="json")
    detail = qc.get("warnings", [])
    qc.update(
        {
            "n_variants": qc_model.n_markers,
            "n_no_calls": qc_model.n_nocalls,
            "het_rate": qc_model.autosomal_het_rate,
            "sex_chrom_counts": qc["sex_chromosomes"],
            "warnings": _warning_strings(detail),
            "warning_details": detail,
        }
    )
    summary: dict[str, Any] = {
        "space": None,
        "sample_names": [sample_name],
        "n_samples": 1,
        "vendor": raw.vendor,
        "build": raw.build,
    }
    panel = science.snp_panel()
    if panel is not None:
        harm = io_mod.harmonize(raw, panel)
        dosage = np.asarray(harm.dosage, dtype=np.float64)
        enc = np.where(np.isnan(dosage), -1, dosage).astype(np.int8)
        ov = harm.overlap.model_dump(mode="json")
        qc.update(
            {"panel_overlap": ov["overlap_fraction"], "panel_size": ov["n_panel"], "overlap": ov}
        )
        qc["warnings"] += _warning_strings([w.model_dump() for w in harm.warnings])
        if ov["n_usable"] < 10_000:
            qc["warnings"].append(
                f"Only {ov['n_usable']} SNPs overlap the reference panel; projections will be "
                "noisy."
            )
        panel_version = f"{panel.name}:{panel.n}"
        meta = {
            "panel_name": harm.panel_name,
            "panel_version": panel_version,
            "panel_n": int(panel.n),
            "build": harm.build,
            "counted_allele": harm.counted_allele,
            "sample_name": sample_name,
        }
        summary.update(harmonized=True, panel=panel_version, n_usable=ov["n_usable"])
        return DatasetPayload("dosage-npz-v1", meta, {"dosage": enc}), qc, summary, panel_version
    a1, a2 = np.asarray(raw.allele1).astype(str), np.asarray(raw.allele2).astype(str)
    called = (a1 != "-") & (a2 != "-")
    arrays = {
        "rsid": np.asarray(raw.rsid).astype(str)[called],
        "chrom": np.asarray(raw.chrom).astype(str)[called],
        "pos": np.asarray(raw.pos).astype(np.int64)[called],
        "allele1": a1[called],
        "allele2": a2[called],
    }
    qc["warnings"].append(
        "Reference SNP panel not installed: calls stored encrypted, to be harmonised later."
    )
    summary.update(harmonized=False)
    meta = {"build": raw.build, "vendor": raw.vendor, "sample_name": sample_name}
    return DatasetPayload("calls-npz-v1", meta, arrays), qc, summary, None


def ingest(
    session: Session,
    vault: DatasetVault,
    principal: Principal,
    *,
    kind: str,
    data: bytes,
    filename: str | None,
    name: str | None,
    expires_at: Any,
) -> Dataset:
    """Parse in memory, encrypt, persist. Raw bytes never touch disk or logs."""
    input_sha = hashlib.sha256(data).hexdigest()
    safe_name = sanitize_filename(filename) if filename else None
    display = (name or (safe_name.rsplit(".", 1)[0] if safe_name else None) or "dataset")[:200]
    io_mod = science._module("strata.io")
    try:
        if kind == "g25":
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            payload, qc, summary = _ingest_g25(text)
            panel_version = None
        else:
            payload, qc, summary, panel_version = _ingest_raw(data, safe_name or "", display)
            got = "vcf" if summary.get("vendor") == "vcf" else "raw_dna"
            if kind == "vcf" and got != "vcf":
                raise ApiError(422, "file is not a VCF", "invalid_input")
            kind = got
    except io_mod.InputFormatError as exc:
        raise ApiError(422, f"could not parse file: {exc}", "invalid_input") from exc
    ds = Dataset(
        id=uuid.uuid4(),
        owner_id=principal.user_id,
        name=display,
        kind=kind,
        original_filename=safe_name,
        size_bytes=len(data),
        input_sha256=input_sha,
        payload_format=payload.format,
        qc_report=qc,
        summary=summary,
        panel_version=panel_version,
        expires_at=expires_at,
    )
    vault.seal(session, ds, _encode(payload))
    session.flush()
    return ds


def detect_kind(data: bytes, filename: str | None) -> str:
    """`auto`: G25 sheets are short CSV rows of a name + 25 numbers; everything else is raw."""
    head = data[:4096].decode("utf-8", errors="replace")
    lines = [ln for ln in head.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return "raw_dna"
    for ln in lines[:3]:
        fields = [f for f in ln.replace("\t", ",").split(",") if f.strip()]
        if len(fields) == 26:
            try:
                [float(x) for x in fields[1:]]
                return "g25"
            except ValueError:
                continue
    return "raw_dna"


# ------------------------------------------------------------------ access


def get_owned(session: Session, principal: Principal, dataset_id: uuid.UUID) -> Dataset:
    ds = session.get(Dataset, dataset_id)
    if ds is None or ds.owner_id != principal.user_id:
        raise ApiError(404, "dataset not found", "not_found")
    return ds


def open_payload(session: Session, vault: DatasetVault, ds: Dataset) -> DatasetPayload:
    return decode_payload(vault.open(session, ds))


def g25_coordinates(payload: DatasetPayload, target: str | None) -> tuple[str, np.ndarray]:
    names: list[str] = payload.meta["names"]
    if target is None:
        if len(names) != 1:
            raise ApiError(422, "dataset has several samples; specify `target`", "invalid_input")
        target = names[0]
    if target not in names:
        raise ApiError(422, f"sample {target!r} not in dataset", "invalid_input")
    return target, payload.arrays["matrix"][names.index(target)]


def to_out(ds: Dataset) -> dict[str, Any]:
    return {
        "id": ds.id,
        "name": ds.name,
        "kind": ds.kind,
        "space": ds.summary.get("space"),
        "sample_names": ds.summary.get("sample_names", []),
        "created_at": ds.created_at,
        "expires_at": ds.expires_at,
        "qc": ds.qc_report,
        "summary": ds.summary,
        "input_sha256": ds.input_sha256,
        "payload_sha256": ds.payload_sha256,
        "size_bytes": ds.size_bytes,
    }
