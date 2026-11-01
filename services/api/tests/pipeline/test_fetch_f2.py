"""Tests for fetching a published f2 cache.

This code unpacks an archive downloaded over the network into the data
directory, and the cache it installs fixes the SNP set for every statistic
computed afterwards. So each check it makes gets a test: a wrong checksum, an
archive that writes outside its destination, and a cache that does not match
the committed manifest must all fail with nothing left in place.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from pipeline import fetchf2
from pipeline.fetchf2 import FetchError, asset_url, count_populations, fetch_f2

REF = "strata-ref-v1"


def _make_cache_archive(path: Path, pops: list[str], *, root: str = REF) -> None:
    """Write a tarball shaped like the one `build-reference.yml` publishes."""
    with tarfile.open(path, "w:gz") as archive:
        for pop in pops:
            info = tarfile.TarInfo(f"{root}/{pop}/f2.rds")
            payload = f"blocks for {pop}".encode()
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _publish(tmp_path: Path, pops: list[str], **kwargs: object) -> dict[str, bytes]:
    """Return a URL -> bytes map standing in for the release assets."""
    tarball = tmp_path / "asset.tar.gz"
    _make_cache_archive(tarball, pops, **kwargs)  # type: ignore[arg-type]
    blob = tarball.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    asset = fetchf2.ASSET_TEMPLATE.format(reference_version=REF)
    url = asset_url(fetchf2.DEFAULT_REPO, f"reference-{REF}", asset)
    return {url: blob, f"{url}.sha256": f"{digest}  {asset}\n".encode()}


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch):
    """Serve a URL -> bytes map in place of the network."""

    def install(responses: dict[str, bytes]) -> None:
        def fake_download(url: str, dest: Path) -> None:
            if url not in responses:
                raise FetchError(f"{url} returned 404")
            dest.write_bytes(responses[url])

        monkeypatch.setattr(fetchf2, "_download", fake_download)

    return install


def _layout(tmp_path: Path, *, n_pops: int | None = None) -> tuple[Path, Path]:
    derived = tmp_path / "derived"
    derived.mkdir()
    if n_pops is not None:
        (derived / "MANIFEST.json").write_text(json.dumps({"f2": {"n_pops": n_pops}}))
    return derived, tmp_path / "work"


def test_a_verified_cache_is_installed(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path, n_pops=2)
    served(_publish(tmp_path, ["Mbuti", "Kalash"]))

    result = fetch_f2(derived=derived, work=work, reference_version=REF)

    assert result.n_pops == 2
    assert not result.skipped
    assert (derived / "f2" / REF / "Mbuti" / "f2.rds").is_file()


def test_a_wrong_checksum_installs_nothing(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path)
    responses = _publish(tmp_path, ["Mbuti"])
    (url,) = [u for u in responses if u.endswith(".sha256")]
    responses[url] = b"%s  asset\n" % (b"0" * 64)
    served(responses)

    with pytest.raises(FetchError, match="checksum mismatch"):
        fetch_f2(derived=derived, work=work, reference_version=REF)

    assert not (derived / "f2").exists()


def test_a_cache_that_disagrees_with_the_manifest_is_refused(
    tmp_path: Path, served
) -> None:
    """A mismatched cache would change p-values rather than fail loudly."""
    derived, work = _layout(tmp_path, n_pops=136)
    served(_publish(tmp_path, ["Mbuti", "Kalash"]))

    with pytest.raises(FetchError, match="MANIFEST.json records 136"):
        fetch_f2(derived=derived, work=work, reference_version=REF)

    assert not (derived / "f2" / REF).exists()


def test_an_archive_that_escapes_its_destination_is_refused(
    tmp_path: Path, served
) -> None:
    derived, work = _layout(tmp_path)
    served(_publish(tmp_path, ["../../escaped"]))

    with pytest.raises(FetchError, match="outside"):
        fetch_f2(derived=derived, work=work, reference_version=REF)

    assert not (tmp_path.parent / "escaped").exists()


def test_an_archive_rooted_elsewhere_is_refused(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path)
    served(_publish(tmp_path, ["Mbuti"], root="some-other-reference"))

    with pytest.raises(FetchError, match="outside"):
        fetch_f2(derived=derived, work=work, reference_version=REF)


def test_a_link_member_is_refused(tmp_path: Path, served) -> None:
    """A symlink in the archive can redirect a later write out of the tree."""
    derived, work = _layout(tmp_path)
    tarball = tmp_path / "asset.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        info = tarfile.TarInfo(f"{REF}/Mbuti")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc"
        archive.addfile(info)
    blob = tarball.read_bytes()
    asset = fetchf2.ASSET_TEMPLATE.format(reference_version=REF)
    url = asset_url(fetchf2.DEFAULT_REPO, f"reference-{REF}", asset)
    served(
        {
            url: blob,
            f"{url}.sha256": f"{hashlib.sha256(blob).hexdigest()}  {asset}\n".encode(),
        }
    )

    with pytest.raises(FetchError, match="link member"):
        fetch_f2(derived=derived, work=work, reference_version=REF)


def test_an_existing_cache_is_left_alone(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path)
    kept = derived / "f2" / REF / "Mbuti"
    kept.mkdir(parents=True)
    served({})  # any download would 404

    result = fetch_f2(derived=derived, work=work, reference_version=REF)

    assert result.skipped
    assert result.n_pops == 1


def test_force_replaces_an_existing_cache(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path)
    stale = derived / "f2" / REF / "Stale"
    stale.mkdir(parents=True)
    served(_publish(tmp_path, ["Mbuti", "Kalash"]))

    result = fetch_f2(derived=derived, work=work, reference_version=REF, force=True)

    assert result.n_pops == 2
    assert not stale.exists()


def test_bookkeeping_directories_are_not_counted_as_populations(tmp_path: Path) -> None:
    """`extract_f2.R` excludes these, so the manifest check must too."""
    f2_dir = tmp_path / REF
    for name in ("Mbuti", "indivs", "pairs"):
        (f2_dir / name).mkdir(parents=True)

    assert count_populations(f2_dir) == 1


def test_a_malformed_sidecar_is_refused(tmp_path: Path, served) -> None:
    derived, work = _layout(tmp_path)
    responses = _publish(tmp_path, ["Mbuti"])
    (url,) = [u for u in responses if u.endswith(".sha256")]
    responses[url] = b"not-a-digest\n"
    served(responses)

    with pytest.raises(FetchError, match="malformed"):
        fetch_f2(derived=derived, work=work, reference_version=REF)
