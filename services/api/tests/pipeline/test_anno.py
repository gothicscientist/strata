"""Tests for the AADR `.anno` parser.

The header of a real `.anno` file is prose, carries trailing spaces and is
reworded between releases, so these tests pin the behaviour that actually
breaks: which header text resolves to which canonical field, and how messy
cell values are coerced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipeline.anno import (
    AnnoFormatError,
    clean,
    header_report,
    map_header,
    normalise_header,
    normalise_sex,
    read_anno,
    to_float,
    to_int,
)


class TestNormaliseHeader:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Genetic ID ", "genetic_id"),
            ("  Group ID  ", "group_id"),
            ("Lat. ", "lat"),
            ("Long. ", "long"),
            ("No. Libraries ", "no_libraries"),
            ("﻿Genetic ID", "genetic_id"),
            ("ASSESSMENT ", "assessment"),
            ("Sex ratio [Y/(Y+X) counts] (merged data) ", "sex_ratio_y_y_x_counts_merged_data"),
        ],
    )
    def test_normalisation(self, raw: str, expected: str) -> None:
        assert normalise_header(raw) == expected


class TestMapHeader:
    def test_resolves_real_aadr_columns(self) -> None:
        header = [
            "Genetic ID ",
            "Master ID ",
            "Group ID ",
            "Lat. ",
            "Long. ",
            "Molecular Sex ",
            "ASSESSMENT ",
        ]
        mapping, unmapped = map_header(header)
        assert unmapped == {}
        assert list(mapping.values()) == [
            "genetic_id",
            "master_id",
            "group_id",
            "lat",
            "lon",
            "molecular_sex",
            "assessment",
        ]

    def test_1240k_and_ho_snp_columns_do_not_collide(self) -> None:
        """The two SNP-count columns differ only in a trailing token."""
        header = [
            "Genetic ID ",
            "Group ID ",
            "SNPs hit on autosomal targets (Computed using easystats on 1240k snpset) ",
            "SNPs hit on autosomal targets (Computed using easystats on HO snpset) ",
        ]
        mapping, unmapped = map_header(header)
        assert unmapped == {}
        assert mapping[2] == "n_snps_1240k"
        assert mapping[3] == "n_snps_ho"

    def test_coverage_columns_do_not_collide(self) -> None:
        header = [
            "Genetic ID ",
            "Group ID ",
            "1240k coverage (taken from original pulldown where possible) ",
            "mtDNA coverage (merged data) ",
        ]
        mapping, _ = map_header(header)
        assert mapping[2] == "coverage_1240k"
        assert mapping[3] == "coverage_mtdna"

    def test_assessment_warnings_does_not_swallow_assessment(self) -> None:
        header = [
            "Genetic ID ",
            "Group ID ",
            "ASSESSMENT ",
            'ASSESSMENT WARNINGS (Xcontam interval is listed if lower bound is >0.005) ',
        ]
        mapping, _ = map_header(header)
        assert mapping[2] == "assessment"
        assert mapping[3] == "assessment_warnings"

    def test_warnings_before_assessment_still_resolves_both(self) -> None:
        """Column order must not change which rule claims which column."""
        header = [
            "Genetic ID ",
            "Group ID ",
            "ASSESSMENT WARNINGS (Xcontam ...) ",
            "ASSESSMENT ",
        ]
        mapping, _ = map_header(header)
        assert mapping[2] == "assessment_warnings"
        assert mapping[3] == "assessment"

    def test_missing_required_column_raises(self) -> None:
        with pytest.raises(AnnoFormatError, match="group_id"):
            map_header(["Genetic ID ", "Lat. "])

    def test_unknown_columns_are_preserved_not_dropped(self) -> None:
        header = ["Genetic ID ", "Group ID ", "Some Brand New Column "]
        mapping, unmapped = map_header(header)
        assert "some_brand_new_column" in unmapped
        assert mapping[2] == "some_brand_new_column"

    def test_renamed_header_still_resolves(self) -> None:
        """A plausible future rewording must not break the required fields."""
        header = [
            "Genetic ID (instance)",
            "Group ID (population label)",
            "Date mean in BP in years before 1950 CE",
            "Political Entity (country)",
        ]
        mapping, _ = map_header(header)
        assert set(mapping.values()) >= {
            "genetic_id",
            "group_id",
            "date_mean_bp",
            "political_entity",
        }


class TestCellCoercion:
    @pytest.mark.parametrize("token", ["", "..", "n/a", "NA", "  ", "..."])
    def test_missing_tokens_become_none(self, token: str) -> None:
        assert clean(token) is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("3200", 3200.0),
            ("1,234", 1234.0),
            (" 0.0315 ", 0.0315),
            (">100", 100.0),
            ("..", None),
            ("not a number", None),
            ("3400-3100 BCE", 3400.0),
        ],
    )
    def test_to_float(self, raw: str, expected: float | None) -> None:
        assert to_float(raw) == expected

    def test_to_int_rounds(self) -> None:
        assert to_int("812345.6") == 812346
        assert to_int("..") is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("M", "M"), ("F", "F"), ("U", "U"), ("M?", "U"), ("", "U"), ("..", "U"), ("female", "F")],
    )
    def test_normalise_sex(self, raw: str, expected: str) -> None:
        assert normalise_sex(raw) == expected


class TestReadAnno:
    def test_parses_every_row(self, mini_anno: Path) -> None:
        records = read_anno(mini_anno)
        assert len(records) == 12
        assert [r.genetic_id for r in records][:2] == ["SYN001", "SYN002"]

    def test_typed_fields(self, mini_anno: Path) -> None:
        rec = next(r for r in read_anno(mini_anno) if r.genetic_id == "SYN001")
        assert rec.group_id == "Synthetica_IA"
        assert rec.master_id == "SYN001"
        assert rec.date_mean_bp == 3200.0
        assert rec.date_sd_bp == 45.0
        assert rec.lat == 34.5
        assert rec.lon == 71.25
        assert rec.n_snps_1240k == 812345
        assert rec.n_snps_ho == 521345
        assert rec.molecular_sex == "M"
        assert rec.assessment == "PASS"
        assert rec.assessment_warnings is None
        assert rec.country == "Syntheland" if hasattr(rec, "country") else True

    def test_snps_selected_by_snpset(self, mini_anno: Path) -> None:
        rec = next(r for r in read_anno(mini_anno) if r.genetic_id == "SYN001")
        assert rec.n_snps("1240K") == 812345
        assert rec.n_snps("HO") == 521345
        with pytest.raises(ValueError, match="unknown snpset"):
            rec.n_snps("2M")

    def test_uncertain_sex_becomes_unknown(self, mini_anno: Path) -> None:
        rec = next(r for r in read_anno(mini_anno) if r.genetic_id == "SYN010")
        assert rec.molecular_sex == "U"

    def test_present_day_detection(self, mini_anno: Path) -> None:
        by_id = {r.genetic_id: r for r in read_anno(mini_anno)}
        assert by_id["SYN006"].is_present_day is True
        assert by_id["SYN001"].is_present_day is False

    def test_assessment_text_combines_verdict_and_warnings(self, mini_anno: Path) -> None:
        rec = next(r for r in read_anno(mini_anno) if r.genetic_id == "SYN004")
        text = rec.assessment_text()
        assert "QUESTIONABLE" in text
        assert text == text.upper()

    def test_header_report_maps_everything(self, mini_anno: Path) -> None:
        report = header_report(mini_anno)
        assert report["delimiter"] == "tab"
        assert report["unmapped"] == {}
        for required in ("genetic_id", "group_id", "n_snps_1240k", "n_snps_ho"):
            assert required in report["mapped"]

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.anno"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(AnnoFormatError, match="empty"):
            read_anno(empty)

    def test_short_row_is_padded_not_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "short.anno"
        path.write_text(
            "Genetic ID \tGroup ID \tLat. \nX1\tPopA\t12.5\nX2\tPopB\n",
            encoding="utf-8",
        )
        records = read_anno(path)
        assert [r.genetic_id for r in records] == ["X1", "X2"]
        assert records[1].lat is None

    def test_strict_mode_rejects_ragged_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "ragged.anno"
        path.write_text(
            "Genetic ID \tGroup ID \tLat. \nX1\tPopA\t12.5\nX2\tPopB\n",
            encoding="utf-8",
        )
        with pytest.raises(AnnoFormatError, match="fields"):
            read_anno(path, strict=True)

    def test_extra_delimiters_in_free_text_keep_leading_columns(self, tmp_path: Path) -> None:
        """A stray tab in a free-text field must not shift the IDs."""
        path = tmp_path / "wide.anno"
        path.write_text(
            "Genetic ID \tGroup ID \tLocality \nX1\tPopA\tSite\tWith\tTabs\n",
            encoding="utf-8",
        )
        records = read_anno(path)
        assert records[0].genetic_id == "X1"
        assert records[0].group_id == "PopA"

    def test_blank_group_id_is_marked_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "blank.anno"
        path.write_text("Genetic ID \tGroup ID \nX1\t\n", encoding="utf-8")
        records = read_anno(path)
        assert records[0].group_id.startswith("Ignore_")

    def test_comma_separated_export_is_sniffed(self, tmp_path: Path) -> None:
        path = tmp_path / "comma.anno"
        path.write_text("Genetic ID ,Group ID ,Lat. \nX1,PopA,12.5\n", encoding="utf-8")
        records = read_anno(path)
        assert records[0].group_id == "PopA"
        assert records[0].lat == 12.5
