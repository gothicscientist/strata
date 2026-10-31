"""Consumer raw-DNA parsing with format autodetection.

Supported: 23andMe (v3/v4/v5 exports), AncestryDNA (v1/v2), FTDNA Family Finder and MyHeritage
CSV, Living DNA, and single-sample VCF (plain, gzip or BGZF). Uploads may be ``.zip`` or ``.gz``
archives wrapping one file. Parsing is vectorised with pandas (C engine).

Genotype content is never logged or put into warning messages.
"""

from __future__ import annotations

import gzip
import io
import re
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from strata.io.errors import InputFormatError
from strata.io.types import (
    Build,
    InferredSex,
    ParseWarning,
    QCReport,
    RawGenotypes,
    SexChromCounts,
    Vendor,
)

NOCALL = "-"
_BASES = np.array(["A", "C", "G", "T"])
_CHROM_MAP = {"23": "X", "24": "Y", "25": "XY", "26": "MT", "M": "MT", "MT": "MT", "XY": "XY"}
_VALID_CHROMS = {str(i) for i in range(1, 23)} | {"X", "Y", "XY", "MT"}

# Pseudo-autosomal regions on chrX (1-based, inclusive).
_PAR = {
    "GRCh37": ((60001, 2699520), (154931044, 155260560)),
    "GRCh38": ((10001, 2781479), (155701383, 156030895)),
    "NCBI36": ((1, 2709520), (154584238, 154913754)),
}

# Well-characterised SNPs with distinct GRCh37 / GRCh38 positions, used to vote on the build
# when the header does not state it.
_LANDMARKS: dict[str, tuple[str, int, int]] = {
    "rs4988235": ("2", 136608646, 135851076),  # MCM6 / LCT
    "rs1426654": ("15", 48426484, 48134287),  # SLC24A5
    "rs12913832": ("15", 28365618, 28120472),  # HERC2
    "rs3827760": ("2", 109513601, 108897145),  # EDAR
}
_CONTIG1_LENGTH = {249250621: "GRCh37", 248956422: "GRCh38", 247249719: "NCBI36"}

_MAX_ARCHIVE_MEMBER = 2 * 1024**3


# --------------------------------------------------------------------------- decompression


def _unwrap(data: bytes, filename: str) -> tuple[bytes, str]:
    for _ in range(3):
        if data[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = [
                    m
                    for m in zf.infolist()
                    if not m.is_dir()
                    and not m.filename.startswith("__MACOSX")
                    and not m.filename.rsplit("/", 1)[-1].startswith(".")
                ]
                if len(members) != 1:
                    raise InputFormatError(
                        f"Zip archive must contain exactly one data file (found {len(members)})."
                    )
                if members[0].file_size > _MAX_ARCHIVE_MEMBER:
                    raise InputFormatError("Archived file is too large.")
                filename = members[0].filename
                data = zf.read(members[0])
        elif data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
            filename = filename.removesuffix(".gz")
        else:
            break
    return data, filename


# --------------------------------------------------------------------------- detection


def _head_text(data: bytes, n: int = 65536) -> str:
    return data[:n].decode("utf-8", errors="replace").lstrip("﻿")


def detect_format(head: str) -> Vendor:
    lines = head.splitlines()
    first_data = next((ln for ln in lines if ln.strip() and not ln.startswith("#")), "")
    low = head.lower()
    if head.startswith("##fileformat=VCF"):
        return "vcf"
    if "23andme" in low:
        return "23andme"
    if "ancestrydna" in low or re.match(
        r"^rsid\s+chromosome\s+position\s+allele1\s+allele2", first_data, re.I
    ):
        return "ancestrydna"
    if "living dna" in low or "livingdna" in low:
        return "livingdna"
    norm = first_data.replace('"', "").upper().replace(" ", "")
    if norm.startswith("RSID,CHROMOSOME,POSITION,RESULT"):
        return "myheritage" if "myheritage" in low else "ftdna"
    fields = re.split(r"\t", first_data.strip())
    if len(fields) == 4 and re.fullmatch(r"[ACGTDI\-]{1,2}", fields[3].strip()):
        return "generic"
    raise InputFormatError(
        "Unrecognised raw DNA format. Supported: 23andMe, AncestryDNA, FTDNA, MyHeritage, "
        "Living DNA (text/zip) and single-sample VCF."
    )


def _build_from_number(num: str) -> Build:
    return {"36": "NCBI36", "18": "NCBI36", "37": "GRCh37", "19": "GRCh37", "38": "GRCh38"}.get(
        num, "unknown"
    )


def _build_from_header(head: str, vendor: Vendor) -> Build:
    comments = "\n".join(ln for ln in head.splitlines() if ln.startswith("#"))
    if vendor == "vcf":
        m = re.search(r"##contig=<ID=(?:chr)?1,length=(\d+)", comments)
        if m and int(m.group(1)) in _CONTIG1_LENGTH:
            return _CONTIG1_LENGTH[int(m.group(1))]  # type: ignore[return-value]
        m = re.search(r"##reference=.*", comments)
        if m:
            ref = m.group(0).lower()
            if re.search(r"grch38|hg38|hs38|b38", ref):
                return "GRCh38"
            if re.search(r"grch37|hg19|hs37|b37|human_g1k_v37", ref):
                return "GRCh37"
        m = re.search(r"##(?:assembly|source)=.*?(GRCh3[78]|hg19|hg38)", comments, re.I)
        if m:
            return "GRCh38" if m.group(1).lower() in ("grch38", "hg38") else "GRCh37"
        return "unknown"
    m = re.search(r"(?:assembly|reference)?\s*build\s*(\d{2})", comments, re.I)
    if m:
        return _build_from_number(m.group(1))
    m = re.search(r"GRCh(3[678])", comments)
    if m:
        return _build_from_number(m.group(1))
    return "unknown"


def _build_from_landmarks(rsid: pd.Series, pos: pd.Series) -> Build:
    votes = {"GRCh37": 0, "GRCh38": 0}
    hits = rsid.isin(list(_LANDMARKS))
    for r, p in zip(rsid[hits], pos[hits], strict=True):
        _, p37, p38 = _LANDMARKS[r]
        if p == p37:
            votes["GRCh37"] += 1
        elif p == p38:
            votes["GRCh38"] += 1
    if votes["GRCh37"] > votes["GRCh38"]:
        return "GRCh37"
    if votes["GRCh38"] > votes["GRCh37"]:
        return "GRCh38"
    return "unknown"


# --------------------------------------------------------------------------- readers
# Readers return a pyarrow Table of string columns rsid, chrom, pos, a1, a2 and a boolean
# column ``single`` (a one-allele call). Parsing uses pyarrow's multithreaded CSV reader.


def _body_after_comments(data: bytes) -> bytes:
    """Strip leading '#' comment lines (vendor headers)."""
    off = 0
    n = len(data)
    while off < n and data[off : off + 1] == b"#":
        nl = data.find(b"\n", off)
        if nl < 0:
            return b""
        off = nl + 1
    return data[off:]


def _read_table(
    body: bytes,
    names: list[str] | None,
    delimiter: str,
    *,
    header: bool,
    include: list[str] | None = None,
) -> pa.Table:
    if not body.strip():
        raise InputFormatError("File contains no genotype rows.")
    read = pacsv.ReadOptions(
        column_names=names,
        autogenerate_column_names=names is None and not header,
        block_size=1 << 22,
    )
    parse = pacsv.ParseOptions(
        delimiter=delimiter,
        quote_char='"',
        invalid_row_handler=lambda _row: "skip",
        newlines_in_values=False,
    )
    conv = pacsv.ConvertOptions(
        include_columns=include,
        check_utf8=False,
        strings_can_be_null=False,
        column_types=None if include is None else dict.fromkeys(include, pa.string()),
    )
    try:
        table = pacsv.read_csv(
            io.BytesIO(body), read_options=read, parse_options=parse, convert_options=conv
        )
    except pa.ArrowInvalid:
        raise InputFormatError("Malformed rows: could not parse the file.") from None
    # Force string type for every column (pyarrow may infer integers).
    return pa.table({c: pc.cast(table[c], pa.string()) for c in table.column_names})


def _split_genotype(g: pa.ChunkedArray) -> tuple[pa.ChunkedArray, pa.ChunkedArray, pa.ChunkedArray]:
    g = pc.utf8_upper(pc.utf8_trim_whitespace(g))
    length = pc.utf8_length(g)
    a1 = pc.utf8_slice_codeunits(g, 0, 1)
    a2 = pc.utf8_slice_codeunits(g, 1, 2)
    single = pc.equal(length, 1)
    a2 = pc.if_else(single, a1, a2)
    empty = pc.equal(length, 0)
    a1 = pc.if_else(empty, NOCALL, a1)
    a2 = pc.if_else(empty, NOCALL, a2)
    return a1, a2, single


def _read_23andme_like(data: bytes) -> pa.Table:
    body = _body_after_comments(data)
    t = _read_table(body, ["rsid", "chrom", "pos", "genotype"], "\t", header=False)
    a1, a2, single = _split_genotype(t["genotype"])
    return pa.table(
        {
            "rsid": t["rsid"],
            "chrom": t["chrom"],
            "pos": t["pos"],
            "a1": a1,
            "a2": a2,
            "single": single,
        }
    )


def _read_ancestry(data: bytes) -> pa.Table:
    body = _body_after_comments(data)
    t = _read_table(body, None, "\t", header=True)
    t = t.rename_columns([c.strip().lower() for c in t.column_names])
    need = ["rsid", "chromosome", "position", "allele1", "allele2"]
    if any(c not in t.column_names for c in need):
        raise InputFormatError("AncestryDNA file is missing required columns.")

    def allele(col: pa.ChunkedArray) -> pa.ChunkedArray:
        x = pc.utf8_upper(pc.utf8_trim_whitespace(col))
        return pc.if_else(pc.equal(x, "0"), NOCALL, x)

    return pa.table(
        {
            "rsid": t["rsid"],
            "chrom": t["chromosome"],
            "pos": t["position"],
            "a1": allele(t["allele1"]),
            "a2": allele(t["allele2"]),
            "single": pa.array(np.zeros(t.num_rows, dtype=bool)),
        }
    )


def _read_ftdna(data: bytes) -> pa.Table:
    body = _body_after_comments(data)
    t = _read_table(body, None, ",", header=True)
    t = t.rename_columns([c.strip().strip('"').upper() for c in t.column_names])
    if any(c not in t.column_names for c in ("RSID", "CHROMOSOME", "POSITION", "RESULT")):
        raise InputFormatError("FTDNA/MyHeritage file is missing required columns.")
    t = t.filter(pc.not_equal(t["RSID"], "RSID"))  # concatenated exports repeat the header
    a1, a2, single = _split_genotype(t["RESULT"])
    return pa.table(
        {
            "rsid": t["RSID"],
            "chrom": t["CHROMOSOME"],
            "pos": t["POSITION"],
            "a1": a1,
            "a2": a2,
            "single": single,
        }
    )


def _read_vcf(data: bytes, sample: str | None) -> pa.Table:
    idx = data.find(b"\n#CHROM")
    if idx < 0:
        raise InputFormatError("VCF has no #CHROM header line.")
    end = data.find(b"\n", idx + 1)
    cols = data[idx + 1 : end].decode().rstrip("\r").split("\t")
    samples = cols[9:]
    if not samples:
        raise InputFormatError("VCF contains no sample genotype column.")
    if sample is None:
        if len(samples) != 1:
            raise InputFormatError(
                f"VCF has {len(samples)} samples; only single-sample VCFs are supported."
            )
        si = 9
    else:
        if sample not in samples:
            raise InputFormatError("Requested VCF sample not found.")
        si = 9 + samples.index(sample)
    names = [f"c{i}" for i in range(len(cols))]
    use = ["c0", "c1", "c2", "c3", "c4", "c8", f"c{si}"]
    t = _read_table(data[end + 1 :], names, "\t", header=False, include=use)
    chrom, pos, vid, ref, alt, fmt, smp = (t[c] for c in use)
    ref = pc.utf8_upper(ref)
    alt = pc.utf8_upper(alt)
    n = t.num_rows

    # GT is the first FORMAT key by VCF spec; handle other orders per distinct FORMAT string.
    gt_first = pc.starts_with(fmt, "GT")
    if pc.all(gt_first).as_py():
        gt = pc.list_element(pc.split_pattern(smp, ":", max_splits=1), 0)
        gt_np = None
    else:
        fmt_np = fmt.to_numpy(zero_copy_only=False)
        smp_np = smp.to_numpy(zero_copy_only=False)
        gt_np = np.full(n, "./.", dtype=object)
        for f in np.unique(fmt_np):
            keys = str(f).split(":")
            if "GT" not in keys:
                continue
            k = keys.index("GT")
            m = fmt_np == f
            gt_np[m] = [x.split(":")[k] if x.count(":") >= k else "./." for x in smp_np[m]]
        gt = pa.array(gt_np, type=pa.string())
    gt = pc.replace_substring(gt, "|", "/")
    parts = pc.split_pattern(gt, "/")
    nparts = pc.list_value_length(parts).to_numpy(zero_copy_only=False)
    first = pc.list_element(parts, 0)
    second = pc.list_element(pc.split_pattern(pc.binary_join_element_wise(gt, first, "/"), "/"), 1)

    alt0 = pc.list_element(pc.split_pattern(alt, ",", max_splits=1), 0)
    ref_np = ref.to_numpy(zero_copy_only=False)
    alt0_np = alt0.to_numpy(zero_copy_only=False)
    i1 = first.to_numpy(zero_copy_only=False)
    i2 = second.to_numpy(zero_copy_only=False)

    def pick(ix: np.ndarray) -> np.ndarray:
        out = np.where(ix == "0", ref_np, np.where(ix == "1", alt0_np, NOCALL)).astype(object)
        other = (ix != "0") & (ix != "1") & (ix != ".")
        if other.any():  # multi-allelic: resolve the few remaining rows in Python
            alt_np = alt.to_numpy(zero_copy_only=False)
            for j in np.flatnonzero(other):
                try:
                    k = int(ix[j])
                    alleles = [ref_np[j], *str(alt_np[j]).split(",")]
                    out[j] = alleles[k] if 0 <= k < len(alleles) else NOCALL
                except ValueError:
                    out[j] = NOCALL
        return out

    a1 = pick(i1)
    a2 = pick(i2)
    ref_len = pc.utf8_length(ref).to_numpy(zero_copy_only=False)
    alt0_len = pc.utf8_length(alt0).to_numpy(zero_copy_only=False)
    symbolic = (alt0_np == ".") | pc.starts_with(alt0, "<").to_numpy(zero_copy_only=False)
    is_indel = (ref_len != 1) | (~symbolic & (alt0_len != 1))
    miss = (i1 == ".") | (i2 == ".")
    bad_len = ~miss & (
        (pd.Series(a1).str.len().to_numpy() != 1) | (pd.Series(a2).str.len().to_numpy() != 1)
    )
    is_indel |= bad_len
    a1 = np.where(is_indel, "I", np.where(miss, NOCALL, a1))
    a2 = np.where(is_indel, "I", np.where(miss, NOCALL, a2))
    rsid = pc.if_else(pc.equal(vid, "."), pc.binary_join_element_wise(chrom, pos, ":"), vid)
    return pa.table(
        {
            "rsid": rsid,
            "chrom": chrom,
            "pos": pos,
            "a1": pa.array(a1, type=pa.string()),
            "a2": pa.array(a2, type=pa.string()),
            "single": pa.array((nparts == 1) & ~miss),
        }
    )


# --------------------------------------------------------------------------- main entry


def _infer_sex(
    chrom: np.ndarray,
    pos: np.ndarray,
    a1: np.ndarray,
    a2: np.ndarray,
    called: np.ndarray,
    build: Build,
) -> tuple[SexChromCounts, InferredSex]:
    is_x = chrom == "X"
    if build in _PAR:
        (p1s, p1e), (p2s, p2e) = _PAR[build]
        par = ((pos >= p1s) & (pos <= p1e)) | ((pos >= p2s) & (pos <= p2e))
        is_x_nonpar = is_x & ~par
    else:
        is_x_nonpar = is_x
    is_y = chrom == "Y"
    x_called = int(np.sum(is_x_nonpar & called))
    x_het = int(np.sum(is_x_nonpar & called & (a1 != a2)))
    y_total = int(np.sum(is_y))
    y_called = int(np.sum(is_y & called))
    x_het_rate = x_het / x_called if x_called else None
    counts = SexChromCounts(
        x=int(np.sum(is_x)),
        y=y_total,
        mt=int(np.sum(chrom == "MT")),
        x_called=x_called,
        y_called=y_called,
        x_het_rate=x_het_rate,
    )
    call: str = "undetermined"
    if x_het_rate is not None and x_called >= 100:
        y_rate = y_called / y_total if y_total else None
        if x_het_rate < 0.02 and (y_rate is None or y_rate > 0.5):
            call = "XY"
        elif x_het_rate > 0.05 and (y_rate is None or y_rate < 0.2):
            call = "XX"
    return counts, InferredSex(call=call)  # type: ignore[arg-type]


def parse_raw_dna(
    data: bytes, filename: str = "", *, vcf_sample: str | None = None
) -> RawGenotypes:
    """Parse a consumer raw-DNA export or single-sample VCF into normalised calls + QC."""
    if not data:
        raise InputFormatError("Empty file.")
    data, filename = _unwrap(data, filename)
    head = _head_text(data)
    vendor = detect_format(head)
    warnings: list[ParseWarning] = []
    if vendor in ("23andme", "livingdna", "generic"):
        t = _read_23andme_like(data)
    elif vendor == "ancestrydna":
        t = _read_ancestry(data)
    elif vendor in ("ftdna", "myheritage"):
        t = _read_ftdna(data)
    else:
        t = _read_vcf(data, vcf_sample)
    n_lines = t.num_rows

    # Chromosome: few distinct values, so normalise the dictionary only.
    chrom_d = pc.dictionary_encode(pc.utf8_upper(pc.utf8_trim_whitespace(t["chrom"])))
    chrom_d = chrom_d.combine_chunks()
    dict_vals = [
        _CHROM_MAP.get(v.removeprefix("CHR"), v.removeprefix("CHR"))
        for v in chrom_d.dictionary.to_pylist()
    ]
    chrom_codes = chrom_d.indices.to_numpy(zero_copy_only=False)
    chrom_np = np.array(dict_vals + ["?"], dtype=object)[chrom_codes]
    valid_chrom = np.array([v in _VALID_CHROMS for v in dict_vals] + [False])[chrom_codes]

    pos_s = pc.utf8_trim_whitespace(t["pos"])
    pos_ok_a = pc.match_substring_regex(pos_s, r"^[0-9]{1,10}$")
    pos_np = pc.cast(pc.if_else(pos_ok_a, pos_s, "0"), pa.int64()).to_numpy(zero_copy_only=False)
    valid_chrom &= pos_ok_a.to_numpy(zero_copy_only=False) & (pos_np > 0)

    bases = pa.array(["A", "C", "G", "T", NOCALL])
    indel_set = pa.array(["D", "I"])
    a1c, a2c = t["a1"], t["a2"]

    def isin(col: pa.ChunkedArray, values: pa.Array) -> np.ndarray:
        return pc.is_in(col, value_set=values).to_numpy(zero_copy_only=False)

    is_indel = isin(a1c, indel_set) | isin(a2c, indel_set)
    ok_allele = isin(a1c, bases) & isin(a2c, bases)
    keep = valid_chrom & ~is_indel & ok_allele
    n_indels = int(np.sum(valid_chrom & is_indel))
    n_invalid = int(np.sum(~keep)) - n_indels

    rsid_c = pc.utf8_trim_whitespace(t["rsid"])
    codes = pc.dictionary_encode(rsid_c).combine_chunks().indices.to_numpy(zero_copy_only=False)
    first_seen = np.zeros(codes.size, dtype=bool)
    kept_idx = np.flatnonzero(keep)
    _, first_pos = np.unique(codes[kept_idx], return_index=True)
    first_seen[kept_idx[first_pos]] = True
    dup = keep & ~first_seen
    n_dup = int(dup.sum())
    keep &= ~dup
    if n_dup:
        warnings.append(
            ParseWarning(
                code="duplicate_markers", message="Dropped repeated marker ids.", count=n_dup
            )
        )
    if n_invalid:
        warnings.append(
            ParseWarning(
                code="invalid_rows",
                message="Dropped rows with unknown chromosome, position or allele codes.",
                count=n_invalid,
            )
        )

    km = pa.array(keep)
    rsid_a = rsid_c.filter(km).to_numpy(zero_copy_only=False)
    chrom_a = chrom_np[keep]
    pos_a = pos_np[keep].astype(np.int64)
    a1_a = a1c.filter(km).to_numpy(zero_copy_only=False)
    a2_a = a2c.filter(km).to_numpy(zero_copy_only=False)
    # A half call (one allele missing) is treated as a no-call.
    half = (a1_a == NOCALL) ^ (a2_a == NOCALL)
    if half.any():
        a1_a = a1_a.copy()
        a2_a = a2_a.copy()
        a1_a[half] = NOCALL
        a2_a[half] = NOCALL
    single = t["single"].filter(km).to_numpy(zero_copy_only=False).astype(bool)
    if rsid_a.size == 0:
        raise InputFormatError("No valid SNP genotype rows found.")

    build = _build_from_header(head, vendor)
    build_source = "header" if build != "unknown" else "unknown"
    lm_build = _build_from_landmarks(pd.Series(rsid_a), pd.Series(pos_a))
    if build == "unknown" and lm_build != "unknown":
        build, build_source = lm_build, "landmarks"
    elif build != "unknown" and lm_build not in ("unknown", build):
        warnings.append(
            ParseWarning(
                code="build_conflict",
                message=f"Header states {build} but landmark SNP positions match {lm_build}.",
            )
        )
    if build == "unknown" and vendor in ("ftdna", "myheritage", "23andme", "ancestrydna"):
        build, build_source = "GRCh37", "assumed"
        warnings.append(
            ParseWarning(
                code="build_assumed",
                message="Genome build not stated; assumed GRCh37 (vendor default).",
            )
        )

    called = a1_a != NOCALL
    n_called = int(called.sum())
    n_markers = int(rsid_a.size)
    autosomal = np.isin(chrom_a, [str(i) for i in range(1, 23)])
    auto_called = autosomal & called
    het_rate = (
        float(np.sum(auto_called & (a1_a != a2_a)) / np.sum(auto_called))
        if auto_called.any()
        else None
    )
    n_haploid = int(np.sum(single & (a1_a != NOCALL)))
    rs_like = pc.starts_with(pa.array(rsid_a, type=pa.string()), "rs")
    n_internal = int(np.sum(~rs_like.to_numpy(zero_copy_only=False)))
    sex_counts, sex = _infer_sex(chrom_a, pos_a, a1_a, a2_a, called, build)

    call_rate = n_called / n_markers
    if call_rate < 0.9:
        warnings.append(
            ParseWarning(
                code="low_call_rate",
                message=f"Call rate {call_rate:.3f} is below 0.90; results may be unreliable.",
            )
        )
    vendor_detail = None
    if vendor == "23andme":
        m = re.search(r"generated by 23andMe at: (.*)", head)
        vendor_detail = f"23andMe export ({m.group(1).strip()})" if m else "23andMe export"
    elif vendor == "ancestrydna":
        arr = re.search(r"array version:?\s*(\S+)", head, re.I)
        fmt = re.search(r"data format version is:?\s*(\S+)", head, re.I)
        parts = ["AncestryDNA"]
        if arr:
            parts.append(f"array {arr.group(1)}")
        if fmt:
            parts.append(f"format {fmt.group(1)}")
        vendor_detail = " ".join(parts)
    qc = QCReport(
        vendor=vendor,
        vendor_detail=vendor_detail,
        build=build,
        build_source=build_source,  # type: ignore[arg-type]
        n_lines=int(n_lines),
        n_markers=n_markers,
        n_called=n_called,
        n_nocalls=n_markers - n_called,
        call_rate=call_rate,
        n_indels_dropped=n_indels,
        n_internal_ids=n_internal,
        n_invalid_dropped=n_invalid,
        n_duplicates_dropped=n_dup,
        n_haploid_calls=n_haploid,
        autosomal_het_rate=het_rate,
        sex_chromosomes=sex_counts,
        inferred_sex=sex,
        warnings=warnings,
    )
    return RawGenotypes(
        vendor=vendor,
        build=build,
        rsid=rsid_a,
        chrom=chrom_a,
        pos=pos_a,
        allele1=a1_a,
        allele2=a2_a,
        qc=qc,
    )
