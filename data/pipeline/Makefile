# Strata reference-data build.
#
#   make all         download -> curate -> pca -> f2 -> manifest
#   make curate      metadata only (no genotypes needed beyond the .anno)
#   make verify      re-hash artefacts against MANIFEST.json
#
# Requires Harvard Dataverse for `download`, and ADMIXTOOLS 2 (via
# STRATA_RSCRIPT) for `f2`. Neither is available in the dev container; CI runs
# this via .github/workflows/build-reference.yml.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT        := $(abspath $(CURDIR)/../..)
PYTHON      ?= $(ROOT)/services/api/.venv/bin/python
AADR_VERSION ?= v66.p1
REF_VERSION  ?= strata-ref-v1
DERIVED     := $(ROOT)/data/derived

# `python -m pipeline` needs this directory on the path, and the `strata`
# package needs services/api on it.
export PYTHONPATH := $(CURDIR):$(ROOT)/services/api$(if $(PYTHONPATH),:$(PYTHONPATH),)
export STRATA_ROOT := $(ROOT)

PIPE := $(PYTHON) -m pipeline --root $(ROOT) --aadr-version $(AADR_VERSION) --reference-version $(REF_VERSION)

.PHONY: help all download curate pca f2 manifest verify citations inspect test clean-work distclean

help:
	@echo "targets:"
	@echo "  download   fetch AADR $(AADR_VERSION) (1240K + HO) from Dataverse"
	@echo "  curate     parse .anno, apply QC, write populations/samples/publications"
	@echo "  pca        fit $(REF_VERSION) PCA space, project individuals"
	@echo "  f2         build the ADMIXTOOLS 2 f2 block cache (slow: hours)"
	@echo "  manifest   hash every artefact into MANIFEST.json"
	@echo "  verify     re-hash artefacts against MANIFEST.json"
	@echo "  all        the full build, in order"
	@echo "  test       unit tests for the parsing and curation logic"
	@echo "  inspect    resolve a .anno header: make inspect ANNO=/path/to/file.anno"

all:
	$(PIPE) all

download:
	$(PIPE) download

curate:
	$(PIPE) curate

pca:
	$(PIPE) pca

f2:
	$(PIPE) f2

manifest:
	$(PIPE) manifest

verify:
	$(PIPE) verify

citations:
	$(PIPE) citations

inspect:
	@test -n "$(ANNO)" || { echo "usage: make inspect ANNO=/path/to/file.anno" >&2; exit 2; }
	$(PIPE) inspect-anno $(ANNO)

test:
	cd $(ROOT)/services/api && .venv/bin/python -m pytest tests/pipeline -q

# Intermediate state only; leaves data/raw and data/derived alone.
clean-work:
	rm -rf $(ROOT)/data/work

# Also removes the downloaded AADR release. The derived artefacts are kept
# because some of them are committed.
distclean: clean-work
	rm -rf $(ROOT)/data/raw/aadr
