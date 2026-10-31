from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from starlette.datastructures import UploadFile

from strata.api import datasets as svc
from strata.api.deps import DbDep, PrincipalDep, SettingsDep, owner_expiry, rate_limit_expensive
from strata.api.errors import ApiError
from strata.api.schemas import DatasetOut
from strata.db.models import Dataset
from strata.security.uploads import UploadRejectedError, validate_upload
from strata.security.vault import vault_from_settings

router = APIRouter(prefix="/datasets", tags=["datasets"])

_UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["g25", "raw_dna", "vcf", "auto"],
                            "default": "auto",
                        },
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "23andMe / AncestryDNA / FTDNA / MyHeritage export, "
                            "single-sample VCF, or G25 CSV (.gz/.zip accepted)",
                        },
                        "g25_text": {"type": "string", "description": "Pasted G25 coordinates"},
                        "name": {"type": "string", "maxLength": 200},
                    },
                }
            }
        },
    }
}


@router.post(
    "",
    response_model=DatasetOut,
    status_code=201,
    openapi_extra=_UPLOAD_SCHEMA,
    dependencies=[Depends(rate_limit_expensive)],
    summary="Upload G25 coordinates or a raw DNA file",
)
async def upload_dataset(
    request: Request, db: DbDep, principal: PrincipalDep, settings: SettingsDep
) -> dict:
    """Parses the upload in memory, harmonises raw DNA to the reference SNP panel (when
    installed), encrypts the result with a per-dataset key, and returns the QC report.
    The original file is never written to disk or logged."""
    form = await request.form(max_files=1, max_fields=6, max_part_size=settings.max_upload_bytes)
    try:
        kind = str(form.get("kind") or "auto")
        if kind not in ("g25", "raw_dna", "vcf", "auto"):
            raise ApiError(422, "kind must be g25, raw_dna, vcf or auto", "invalid_input")
        name = form.get("name")
        name = str(name).strip()[:200] if name else None
        upload = form.get("file")
        text = form.get("g25_text")
        if isinstance(upload, UploadFile):
            raw = await upload.read()
            filename = upload.filename
        elif text:
            raw = str(text).encode()
            filename = "pasted.csv"
            if kind == "auto":
                kind = "g25"
        else:
            raise ApiError(422, "provide `file` or `g25_text`", "invalid_input")
    finally:
        await form.close()
    try:
        accepted = validate_upload(filename, raw, max_bytes=settings.max_upload_bytes)
    except UploadRejectedError as exc:
        raise ApiError(exc.status_code, str(exc), "upload_rejected") from exc
    del raw
    if kind == "auto":
        kind = svc.detect_kind(accepted.data, accepted.filename)
    ds = svc.ingest(
        db,
        vault_from_settings(),
        principal,
        kind=kind,
        data=accepted.data,
        filename=accepted.filename,
        name=name,
        expires_at=owner_expiry(db, principal),
    )
    return svc.to_out(ds)


@router.get("", response_model=list[DatasetOut], summary="List my datasets")
def list_datasets(db: DbDep, principal: PrincipalDep) -> list[dict]:
    rows = (
        db.query(Dataset)
        .filter(Dataset.owner_id == principal.user_id)
        .order_by(Dataset.created_at.desc())
        .all()
    )
    return [svc.to_out(d) for d in rows]


@router.get("/{dataset_id}", response_model=DatasetOut, summary="Dataset metadata + QC")
def get_dataset(dataset_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> dict:
    return svc.to_out(svc.get_owned(db, principal, dataset_id))


@router.delete("/{dataset_id}", status_code=204, summary="Delete (crypto-shred) a dataset")
def delete_dataset(dataset_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> Response:
    """Destroys the dataset's wrapped data key, then its ciphertext and row. Any remaining
    copy of the ciphertext (e.g. in backups) is permanently undecryptable."""
    ds = svc.get_owned(db, principal, dataset_id)
    vault_from_settings().shred(db, ds)
    return Response(status_code=204)
