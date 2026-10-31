"""Error paths of the subprocess bridge.

These do not need ADMIXTOOLS 2: they check that a missing interpreter, a
missing script, a non-existent f2 directory and a malformed result all surface
as the right exception rather than as a traceback from deep inside the parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata.qpadm import (
    QpAdmError,
    QpAdmProtocolError,
    QpAdmSpec,
    QpAdmUnavailable,
    default_f2_dir,
    qpadm_available,
    r_script_dir,
    rscript_path,
    run_qpadm,
)
from strata.qpadm import runner as runner_mod


def spec(**over: object) -> QpAdmSpec:
    base: dict[str, object] = {
        "target": "T",
        "left": ["A", "B"],
        "right": ["R1", "R2", "R3"],
        "f2_dir": "/tmp",
    }
    base.update(over)
    return QpAdmSpec(**base)  # type: ignore[arg-type]


class TestDiscovery:
    def test_script_dir_contains_the_wrappers(self) -> None:
        d = r_script_dir()
        for name in ("common.R", "qpadm.R", "qpadm_rotate.R", "f4.R", "qpwave.R", "extract_f2.R"):
            assert (d / name).is_file(), f"{name} missing from {d}"

    def test_script_dir_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("STRATA_R_DIR", str(tmp_path))
        assert r_script_dir() == tmp_path.resolve()

    def test_rscript_override_must_be_executable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = tmp_path / "Rscript"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("STRATA_RSCRIPT", str(fake))
        assert rscript_path() is None  # not chmod +x
        fake.chmod(0o755)
        assert rscript_path() == str(fake)

    def test_availability_is_a_bool(self) -> None:
        assert isinstance(qpadm_available(), bool)

    def test_missing_rscript_raises_unavailable(self, isolated_r_env: None) -> None:
        with pytest.raises(QpAdmUnavailable, match="Rscript"):
            run_qpadm(spec())

    def test_missing_script_raises_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("STRATA_R_DIR", str(tmp_path))
        if rscript_path() is None:
            pytest.skip("no Rscript to exercise this path")
        with pytest.raises(QpAdmUnavailable, match="wrapper script not found"):
            run_qpadm(spec())


class TestDefaultF2Dir:
    def test_env_override_is_honoured_even_if_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit path must not silently fall back to a different panel."""
        monkeypatch.setenv("STRATA_F2_DIR", "/does/not/exist")
        assert default_f2_dir() == Path("/does/not/exist")

    def test_returns_none_when_nothing_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STRATA_F2_DIR", raising=False)
        monkeypatch.setenv("STRATA_REFERENCE_VERSION", "no-such-version")
        assert default_f2_dir() is None


class TestProtocol:
    def test_malformed_json_is_a_protocol_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A result file that is not JSON must not leak a JSONDecodeError."""

        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
            Path(argv[-1]).write_text("not json at all", encoding="utf-8")
            return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(runner_mod, "rscript_path", lambda: "/bin/true")
        with pytest.raises(QpAdmProtocolError, match="malformed JSON"):
            run_qpadm(spec())

    def test_absent_result_file_is_a_protocol_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
            return type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

        monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(runner_mod, "rscript_path", lambda: "/bin/true")
        with pytest.raises(QpAdmProtocolError, match="no result file"):
            run_qpadm(spec())

    def test_structured_r_error_becomes_a_run_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
            Path(argv[-1]).write_text(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "kind": "analysis_error",
                            "message": "Duplicated pops: A",
                            "r_call": "qpadm(...)",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(runner_mod, "rscript_path", lambda: "/bin/true")
        with pytest.raises(QpAdmError) as excinfo:
            run_qpadm(spec())
        assert "Duplicated pops" in str(excinfo.value)
        assert excinfo.value.kind == "analysis_error"  # type: ignore[attr-defined]

    def test_dependency_missing_maps_to_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
            Path(argv[-1]).write_text(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "kind": "dependency_missing",
                            "message": "the 'admixtools' R package is not installed",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(runner_mod, "rscript_path", lambda: "/bin/true")
        with pytest.raises(QpAdmUnavailable, match="admixtools"):
            run_qpadm(spec())

    def test_r_side_rejects_a_missing_f2_dir(self) -> None:
        """Exercises the real R wrapper, which only needs jsonlite to fail."""
        if rscript_path() is None:
            pytest.skip("no Rscript available")
        with pytest.raises(QpAdmError) as excinfo:
            run_qpadm(spec(f2_dir="/definitely/not/here"))
        message = str(excinfo.value)
        # Without ADMIXTOOLS the dependency check fires first; with it, the
        # directory check does. Either is a clean, structured failure.
        assert "admixtools" in message or "f2_dir" in message
