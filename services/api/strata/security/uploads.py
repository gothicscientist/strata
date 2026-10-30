"""Upload validation: size limits, content sniffing, filename sanitisation."""

from __future__ import annotations

import gzip
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

ALLOWED_EXTENSIONS = {".txt", ".csv", ".tsv", ".vcf", ".gz", ".zip"}
# Hard cap on decompressed size to defuse zip/gzip bombs (raw DNA files are ~15-30 MB).
MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


class UploadRejectedError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AcceptedUpload:
    filename: str
    data: bytes  # decompressed bytes
    compressed: bool


def sanitize_filename(name: str | None, *, max_len: int = 120) -> str:
    """Strip directories, control chars and unusual characters; never returns an empty name."""
    if not name:
        return "upload"
    name = unicodedata.normalize("NFKC", name)
    name = PureWindowsPath(PurePosixPath(name).name).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _SAFE.sub("_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name or set(name) <= {"_", "."}:
        return "upload"
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 8:
            name = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            name = name[:max_len]
    return name


def _looks_textual(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte char may be cut at the sample boundary.
        if exc.start < len(sample) - 4:
            try:
                sample.decode("latin-1")
            except UnicodeDecodeError:
                return False
            # latin-1 decodes anything; require mostly printable ASCII.
            printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in sample)
            return printable / max(len(sample), 1) > 0.95
    return True


def _bounded_read(stream: io.BufferedIOBase | gzip.GzipFile, limit: int) -> bytes:
    out = stream.read(limit + 1)
    if len(out) > limit:
        raise UploadRejectedError("decompressed file exceeds the size limit", 413)
    return out


def validate_upload(filename: str | None, data: bytes, *, max_bytes: int) -> AcceptedUpload:
    """Check size, extension and content; transparently decompress .gz and single-file .zip."""
    safe = sanitize_filename(filename)
    if len(data) == 0:
        raise UploadRejectedError("empty upload")
    if len(data) > max_bytes:
        raise UploadRejectedError(f"upload exceeds {max_bytes // (1024 * 1024)} MB limit", 413)
    lower = safe.lower()
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise UploadRejectedError(f"file type {ext} not accepted", 415)

    compressed = False
    inner_name = safe
    if data[:2] == b"\x1f\x8b":
        compressed = True
        try:
            data = _bounded_read(gzip.GzipFile(fileobj=io.BytesIO(data)), MAX_DECOMPRESSED_BYTES)
        except (OSError, EOFError) as exc:
            raise UploadRejectedError("corrupt gzip file") from exc
        inner_name = safe[:-3] if lower.endswith(".gz") else safe
    elif data[:4] == b"PK\x03\x04":
        compressed = True
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if len(members) != 1:
                    raise UploadRejectedError("zip archives must contain exactly one file")
                m = members[0]
                if m.file_size > MAX_DECOMPRESSED_BYTES:
                    raise UploadRejectedError("decompressed file exceeds the size limit", 413)
                with zf.open(m) as fh:
                    data = _bounded_read(fh, MAX_DECOMPRESSED_BYTES)  # type: ignore[arg-type]
                inner_name = sanitize_filename(m.filename)
        except zipfile.BadZipFile as exc:
            raise UploadRejectedError("corrupt zip file") from exc
    if not data.strip():
        raise UploadRejectedError("file is empty after decompression")
    if not _looks_textual(data[:65536]):
        raise UploadRejectedError("file does not look like a text genotype / coordinate file", 415)
    return AcceptedUpload(filename=inner_name, data=data, compressed=compressed)
