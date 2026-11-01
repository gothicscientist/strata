"""Fetch a prebuilt f2 block cache instead of rebuilding it.

The f2 cache is the one reference artefact that is neither committed nor
cheap: 147 MB for the v66.p1 panel, and ~45 minutes of download, conversion
and extraction to rebuild (plus an ADMIXTOOLS 2 install). It is gitignored, so
a fresh clone — including every deployment — has no cache, and every formal
analysis fails until one exists.

`build-reference.yml` already publishes the cache as a release asset. This is
the other half: the consumer side, so a clone can obtain the same cache the
committed `MANIFEST.json` describes without touching Harvard Dataverse or R.

What is checked, and why each check is here:

* the tarball against the ``.sha256`` published beside it — transport integrity;
* every member path before extraction — a tar archive can name ``../`` or an
  absolute path and write outside the destination, and this archive is
  downloaded over the network;
* the extracted population count against ``MANIFEST.json`` — proves the asset
  is the cache this checkout's manifest refers to, not an older panel. A cache
  fixes the SNP set for every statistic, so a mismatched cache silently
  changes p-values rather than failing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The repository whose releases carry the asset. Overridable so a fork, or a
# mirror inside a deployment, can serve its own build.
DEFAULT_REPO = "gothicscientist/strata"

# Must match the names `build-reference.yml` uploads.
ASSET_TEMPLATE = "f2-{reference_version}.tar.gz"
TAG_TEMPLATE = "reference-{reference_version}"

_CHUNK = 1 << 20

# Not cache entries: `extract_f2.R` excludes these when it counts populations,
# so counting them here would disagree with the manifest.
NON_POP_DIRS = frozenset({"indivs", "pairs"})


class FetchError(RuntimeError):
    """A fetch that cannot be completed, with a message meant for a human."""


@dataclass
class FetchResult:
    f2_dir: Path
    asset: str
    sha256: str
    n_pops: int
    skipped: bool = False  # a usable cache was already in place


def asset_url(repo: str, tag: str, asset: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{asset}"


def _download(url: str, dest: Path) -> None:
    log.info("downloading %s", url)
    try:
        with urllib.request.urlopen(url) as response, dest.open("wb") as out:
            shutil.copyfileobj(response, out, _CHUNK)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FetchError(
                f"{url} returned 404. Either the release has no f2 asset yet "
                f"(run the `Build reference data` workflow with stages=full and "
                f"publish_f2_release=true), or the reference version is wrong."
            ) from exc
        raise FetchError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"{url} is unreachable: {exc.reason}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_digest(text: str) -> str:
    """Read the digest out of a `sha256sum` line."""
    first = text.strip().split("\n")[0].strip()
    digest = first.split()[0] if first else ""
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest.lower()):
        raise FetchError(f"malformed .sha256 sidecar: {first[:80]!r}")
    return digest.lower()


def _safe_members(archive: tarfile.TarFile, root: str) -> list[tarfile.TarInfo]:
    """Return the archive's members, refusing anything that escapes `root`.

    The archive is downloaded over the network, so its member names are
    untrusted input: a name like ``../../etc`` or a symlink pointing out of the
    tree would otherwise write outside the destination directory.
    """
    members: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise FetchError(f"refusing archive member outside the destination: {name!r}")
        if not (name == root or name.startswith(f"{root}/")):
            raise FetchError(f"archive member outside {root!r}: {name!r}")
        if member.issym() or member.islnk():
            raise FetchError(f"refusing link member in the f2 archive: {name!r}")
        if not (member.isfile() or member.isdir()):
            raise FetchError(f"refusing special file in the f2 archive: {name!r}")
        members.append(member)
    if not members:
        raise FetchError("the f2 archive is empty")
    return members


def count_populations(f2_dir: Path) -> int:
    """Count cache entries the way `extract_f2.R` counts them."""
    if not f2_dir.is_dir():
        return 0
    return sum(1 for d in f2_dir.iterdir() if d.is_dir() and d.name not in NON_POP_DIRS)


def manifest_n_pops(manifest: Path) -> int | None:
    """The population count the committed manifest records, if it records one."""
    if not manifest.is_file():
        return None
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8")).get("f2") or {}
    except json.JSONDecodeError as exc:
        raise FetchError(f"{manifest} is not valid JSON: {exc}") from exc
    value = recorded.get("n_pops")
    return int(value) if value is not None else None


def fetch_f2(
    *,
    derived: Path,
    work: Path,
    reference_version: str,
    repo: str = DEFAULT_REPO,
    tag: str | None = None,
    force: bool = False,
) -> FetchResult:
    """Download, verify and unpack the published f2 cache for this reference.

    Args:
        derived: The `data/derived` directory; the cache lands in `f2/`.
        work: Scratch directory for the download.
        reference_version: Names both the asset and the destination directory.
        repo: ``owner/name`` whose release carries the asset.
        tag: Release tag. Defaults to ``reference-<reference_version>``.
        force: Replace a cache that is already in place.

    Returns:
        A :class:`FetchResult`. ``skipped`` is set when a cache was already
        there and `force` was not passed.

    Raises:
        FetchError: On any failed check. Nothing is left in place in that case.
    """
    f2_root = derived / "f2"
    f2_dir = f2_root / reference_version
    expected_pops = manifest_n_pops(derived / "MANIFEST.json")

    existing = count_populations(f2_dir)
    if existing and not force:
        log.info("f2 cache already present: %s (%d populations)", f2_dir, existing)
        return FetchResult(
            f2_dir=f2_dir, asset="", sha256="", n_pops=existing, skipped=True
        )

    asset = ASSET_TEMPLATE.format(reference_version=reference_version)
    tag = tag or TAG_TEMPLATE.format(reference_version=reference_version)
    url = asset_url(repo, tag, asset)

    work.mkdir(parents=True, exist_ok=True)
    tarball = work / asset
    sidecar = work / f"{asset}.sha256"
    _download(url, tarball)
    _download(f"{url}.sha256", sidecar)

    expected = _expected_digest(sidecar.read_text(encoding="utf-8"))
    actual = _sha256(tarball)
    if actual != expected:
        raise FetchError(
            f"checksum mismatch for {asset}: expected {expected}, got {actual}. "
            "The download is corrupt or the asset was replaced; nothing was unpacked."
        )
    log.info("verified %s (sha256 %s)", asset, actual)

    # Unpack beside the destination, then swap, so a failure part-way cannot
    # leave a half-extracted cache that later looks usable.
    staging = work / f"{reference_version}.incoming"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as archive:
        members = _safe_members(archive, reference_version)
        # `filter="data"` is tarfile's own hardening (no absolute paths, links
        # or special files); _safe_members already refuses those, and this
        # keeps the behaviour explicit rather than version-dependent.
        archive.extractall(staging, members=members, filter="data")

    unpacked = staging / reference_version
    n_pops = count_populations(unpacked)
    if not n_pops:
        shutil.rmtree(staging, ignore_errors=True)
        raise FetchError(f"{asset} unpacked no population directories")
    if expected_pops is not None and n_pops != expected_pops:
        shutil.rmtree(staging, ignore_errors=True)
        raise FetchError(
            f"{asset} holds {n_pops} populations but this checkout's "
            f"MANIFEST.json records {expected_pops}. A cache fixes the SNP set "
            "for every statistic computed from it, so the two must agree: "
            "fetch the asset built for this reference version, or rebuild."
        )

    f2_root.mkdir(parents=True, exist_ok=True)
    if f2_dir.exists():
        shutil.rmtree(f2_dir)
    shutil.move(str(unpacked), str(f2_dir))
    shutil.rmtree(staging, ignore_errors=True)
    tarball.unlink(missing_ok=True)
    sidecar.unlink(missing_ok=True)
    log.info("f2 cache ready: %s (%d populations)", f2_dir, n_pops)
    return FetchResult(f2_dir=f2_dir, asset=asset, sha256=actual, n_pops=n_pops)
