"""Resumable, checksummed download of an AADR release.

The AADR lives on Harvard Dataverse (doi:10.7910/DVN/FFIDCW). Dataverse is
unreachable from the development container, so this module is written to run
unattended on a CI runner:

* the dataset's file listing is fetched once and cached as `listing.json`,
  so a rerun does not re-query the API,
* each file is streamed to `<name>.part` and renamed on completion, so an
  interrupted download resumes with an HTTP Range request instead of starting
  over,
* every file's sha256 is computed while streaming and written to a
  `<name>.sha256` sidecar; a rerun verifies the sidecar and skips the
  transfer. Dataverse also publishes a per-file MD5, which is checked when the
  listing provides one.

Nothing here parses genotypes; it only moves bytes and hashes them.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATAVERSE_API, AadrDataset

CHUNK = 1 << 20
USER_AGENT = "strata-reference-pipeline/0.1 (+https://github.com/)"


class DownloadError(RuntimeError):
    """A transfer or integrity check failed."""


def sha256_file(path: Path, *, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _sidecar(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha256")


def record_checksum(path: Path) -> str:
    digest = sha256_file(path)
    _sidecar(path).write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return digest


def verify_checksum(path: Path) -> str | None:
    """Return the recorded digest if it still matches the file, else None."""
    side = _sidecar(path)
    if not path.is_file() or not side.is_file():
        return None
    recorded = side.read_text(encoding="utf-8").split()
    if not recorded:
        return None
    return recorded[0] if sha256_file(path) == recorded[0] else None


def _open(url: str, *, offset: int = 0, timeout: float = 120.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if offset:
        req.add_header("Range", f"bytes={offset}-")
    token = os.environ.get("DATAVERSE_API_TOKEN")
    if token and "dataverse" in url:
        req.add_header("X-Dataverse-key", token)
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_listing(doi: str, dest: Path, *, refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch (and cache) the Dataverse file listing for a dataset DOI."""
    cache = dest / "listing.json"
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    url = f"{DATAVERSE_API}/datasets/:persistentId/?persistentId=doi:{doi}"
    try:
        with _open(url) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise DownloadError(
            f"could not list Dataverse dataset doi:{doi}: {exc}. "
            "Harvard Dataverse must be reachable; run this stage on a runner "
            "with internet access (see .github/workflows/build-reference.yml)."
        ) from exc
    files = payload.get("data", {}).get("latestVersion", {}).get("files", [])
    dest.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(files, indent=1), encoding="utf-8")
    return files


def find_in_listing(files: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Locate one file in a Dataverse listing by its label or filename."""
    for entry in files:
        df = entry.get("dataFile", {})
        candidates = {
            entry.get("label"),
            df.get("filename"),
            df.get("originalFileName"),
        }
        if name in {c for c in candidates if c}:
            return entry
    return None


def download(url: str, path: Path, *, expected_md5: str | None = None) -> str:
    """Stream `url` to `path`, resuming a partial transfer. Returns the sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = verify_checksum(path)
    if existing:
        return existing

    part = path.with_suffix(path.suffix + ".part")
    offset = part.stat().st_size if part.is_file() else 0
    mode = "ab" if offset else "wb"
    try:
        with _open(url, offset=offset) as resp:
            if offset and resp.status != 206:
                # Server ignored the Range header; restart cleanly.
                offset, mode = 0, "wb"
            with part.open(mode) as fh:
                shutil.copyfileobj(resp, fh, CHUNK)
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadError(f"download failed for {url}: {exc}") from exc

    if expected_md5:
        h = hashlib.md5()
        with part.open("rb") as fh:
            for block in iter(lambda: fh.read(CHUNK), b""):
                h.update(block)
        if h.hexdigest() != expected_md5:
            part.unlink(missing_ok=True)
            raise DownloadError(
                f"MD5 mismatch for {path.name}: Dataverse published {expected_md5}, "
                f"got {h.hexdigest()}. The partial file was removed; rerun to retry."
            )

    part.replace(path)
    return record_checksum(path)


def extract_archive(archive: Path, dest: Path) -> list[Path]:
    """Extract an AADR `.tar`/`.tar.gz`, refusing paths that escape `dest`.

    AADR ships each dataset as a tar of `.geno`/`.snp`/`.ind`/`.anno`. The
    archive is third-party data, so member paths are validated before any
    write and members are flattened into `dest`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if not name or name.startswith("."):
                continue
            target = dest / name
            if not target.resolve().is_relative_to(dest.resolve()):
                raise DownloadError(f"archive member escapes destination: {member.name}")
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as fh:
                shutil.copyfileobj(src, fh, CHUNK)
            record_checksum(target)
            written.append(target)
    return written


@dataclass
class FetchResult:
    dataset: str
    files: dict[str, str]  # filename -> sha256
    directory: Path
    notes: list[str]


def fetch_dataset(
    dataset: AadrDataset,
    dest: Path,
    *,
    listing: list[dict[str, Any]] | None = None,
    doi: str | None = None,
) -> FetchResult:
    """Download and unpack one AADR dataset, skipping work already done.

    Dataverse may expose the dataset either as individual files or as one tar
    per snpset; both shapes are handled. The result records a sha256 for every
    file that ends up on disk, which the MANIFEST then carries.
    """
    dest.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    digests: dict[str, str] = {}

    present = [f for f in dataset.files if verify_checksum(dest / f)]
    if len(present) == len(dataset.files):
        return FetchResult(
            dataset=dataset.key,
            files={f: verify_checksum(dest / f) or "" for f in dataset.files},
            directory=dest,
            notes=["all files already present and verified"],
        )

    if listing is None:
        if doi is None:
            raise DownloadError("fetch_dataset needs either a listing or a DOI")
        listing = fetch_listing(doi, dest)

    # Prefer a per-snpset tar when the release publishes one.
    archive_names = (f"{dataset.stem}.tar", f"{dataset.stem}.tar.gz", f"{dataset.stem}.tgz")
    for archive_name in archive_names:
        entry = find_in_listing(listing, archive_name)
        if entry is None:
            continue
        df = entry["dataFile"]
        url = f"{DATAVERSE_API}/access/datafile/{df['id']}?format=original"
        archive = dest / archive_name
        digests[archive_name] = download(url, archive, expected_md5=df.get("md5"))
        for extracted in extract_archive(archive, dest):
            digests[extracted.name] = verify_checksum(extracted) or ""
        notes.append(f"extracted {archive_name}")
        return FetchResult(dataset.key, digests, dest, notes)

    # Otherwise fetch the four files individually.
    missing: list[str] = []
    for name in dataset.files:
        path = dest / name
        existing = verify_checksum(path)
        if existing:
            digests[name] = existing
            continue
        entry = find_in_listing(listing, name)
        if entry is None:
            missing.append(name)
            continue
        df = entry["dataFile"]
        url = f"{DATAVERSE_API}/access/datafile/{df['id']}?format=original"
        digests[name] = download(url, path, expected_md5=df.get("md5"))

    if missing:
        raise DownloadError(
            f"AADR release {dataset.stem} is missing {', '.join(missing)} in the "
            f"Dataverse listing. The release may have renamed its files; check "
            f"the dataset page and update data/pipeline/pipeline/config.py. "
            f"Listing had {len(listing)} entries."
        )
    return FetchResult(dataset.key, digests, dest, notes)
