"""Log redaction: a logging.Filter that refuses records carrying genotype-like payloads.

Genetic data must never reach logs. The filter inspects the rendered message and args and
replaces anything that looks like genotype rows (rsIDs with calls, VCF records, long runs of
allele calls or dosage vectors) with a fixed marker. It is installed on the root logger.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[redacted: genotype-like payload]"

_PATTERNS = [
    # 23andMe / Ancestry rows: rs123 <tab> 1 <tab> 12345 <tab> AG  (or A G)
    re.compile(
        r"\b(?:rs|i)\d{3,}\s*[\t,; ]\s*(?:chr)?[0-9XYMT]{1,2}\s*[\t,; ]\s*\d+"
        r"\s*[\t,; ]\s*[ACGTDI\-0]{1,2}\b",
        re.I,
    ),
    # rsID immediately followed by a genotype call: rs123 AG / rs123:AG / "rs123": "AG"
    re.compile(r"\brs\d{3,}\W{1,4}[ACGT]{2}\b"),
    # VCF data lines: CHROM POS ID REF ALT ... GT
    re.compile(r"(?m)^(?:chr)?[0-9XYMT]{1,2}\t\d+\t\S+\t[ACGTN]+\t[ACGTN.,<>*]+\t"),
    re.compile(r"\b[01.][/|][01.]\b(?:.*\b[01.][/|][01.]\b){4,}"),
    # long runs of diploid calls: AA AG GG TT ...
    re.compile(r"(?:\b[ACGT]{2}\b[\s,;]+){12,}"),
    # long dosage vectors: 0, 1, 2, 2, 1, ... or [0.0, 2.0, ...]
    re.compile(r"(?:\b[012](?:\.0)?\s*[,\s]\s*){40,}"),
]


def looks_like_genotypes(text: str) -> bool:
    if len(text) < 8:
        return False
    return any(p.search(text) for p in _PATTERNS)


class GenotypeRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - malformed format args: drop them
            msg = str(record.msg)
        if looks_like_genotypes(msg) or (record.exc_text and looks_like_genotypes(record.exc_text)):
            record.msg = REDACTED
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True


_installed = False


def install_log_redaction(level: str = "INFO") -> None:
    global _installed
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if _installed:
        return
    flt = GenotypeRedactionFilter()
    # Filters on handlers apply to records from every logger that propagates to them.
    for h in root.handlers:
        h.addFilter(flt)
    root.addFilter(flt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "strata", "sqlalchemy.engine"):
        logging.getLogger(name).addFilter(flt)
    _installed = True
