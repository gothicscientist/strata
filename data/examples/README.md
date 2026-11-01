# Worked examples

Real, reproducible f-statistic analyses, one directory per example:

```
data/examples/<slug>/example.json
```

Each `example.json` carries `{slug, title, summary, kind, result_kind, tags,
description, caveats, inputs, params, result, provenance}`. `result` is the
serialised pydantic result model, so it holds the same fields the API returns.
`provenance` records the ADMIXTOOLS 2 and R versions, the platform, the command,
a UTC timestamp, and the sha256 of both the input spec and the result.

## These are computations, not fixtures

`generate_examples.py` runs ADMIXTOOLS 2 for real. **If ADMIXTOOLS 2 is
unavailable it exits non-zero and writes nothing.** An absent example directory
therefore means "not yet computed" — never a fabricated result.

```bash
# from the repository root, with the R environment built
export STRATA_RSCRIPT=$(services/worker/r/install_env.sh)
services/api/.venv/bin/python data/examples/generate_examples.py
```

## What the current examples are, and are not

They run on `admixtools::example_f2_blocks`, the f2-statistics bundled with
ADMIXTOOLS 2 for seven populations: Altai Neanderthal, Vindija, Denisova, Mbuti,
Chimp, Russia_Ust_Ishim and Switzerland_Bichon.

* These are **real data** and the statistics computed from them are **genuine**.
* They are the package's **demonstration populations** — archaic hominins and
  Palaeolithic modern humans.
* **They are not a South Asian analysis** and must never be presented as one.
  Every record repeats this in its `caveats` field, and any UI rendering an
  example must show those caveats.

South Asian examples need the AADR reference panel, which `data/pipeline/`
builds on a machine that can reach Harvard Dataverse. Once a panel and its f2
cache exist, add the corresponding analyses to `build_examples()`.

The planned examples cover a one-source fit (a cladality test), a two-source
fit, rotation over a candidate pool, f4 symmetry tests, and a qpWave rank test —
chosen so a reader sees what a *rejected* model looks like, not only a flattering
one.

## Licensing

ADMIXTOOLS 2 and its bundled data are GPL-3. No AADR genotypes are redistributed
here. See `docs/DATA_PROVENANCE.md`.
