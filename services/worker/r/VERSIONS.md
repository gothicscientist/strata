# Pinned R environment for the f-statistics worker

Produced by `services/worker/r/install_env.sh` on `linux-64`.
`install_env.sh` also writes this list to `$PREFIX/strata-r-versions.txt` at
install time, so a running container can report exactly what it has.

## Pins

| Component | Pin |
|---|---|
| micromamba | 2.10.0 build 0 (conda-forge) |
| R | `r-base>=4.4,<4.6` |
| ADMIXTOOLS 2 | `uqrmaie1/admixtools` @ `472d04e98ac8aa70e5c9cbe65722c7e5dfbe8200` (DESCRIPTION `Version: 2.0.10`, GPL-3) |

## Resolved versions

Recorded from an actual `install_env.sh` run of the conda-forge solve
(2026-10-30). `admixtools` itself is built from the pinned commit.

```
R version 4.5.3 (2026-03-11)
abind            1.4.8
cli              3.6.6
crayon           1.5.3
cubelyr          1.0.2
data.tree        1.2.0
digest           0.6.39
doParallel       1.0.17
dplyr            1.2.1
foreach          1.5.2
furrr            0.4.0
future           1.80.0
ggplot2          4.0.3
igraph           2.3.4
jsonlite         2.0.0
lobstr           1.2.2
magrittr         2.0.5
parallelly       1.48.0
pgenlibr         0.7.0
quadprog         1.5.8
purrr            1.2.2
Rcpp             1.1.2
RcppArmadillo    15.6.2.1
readr            2.2.0
rlang            1.3.0
stringi          1.8.9
stringr          1.6.0
tibble           3.3.1
tidyr            1.3.2
genio            1.1.2
testthat         3.3.2
admixtools       2.0.10 (from pinned commit)
```

## Notes

* **CRAN is unreachable** from the build environment, so every dependency is a
  conda-forge package. `r-cubelyr` only exists in conda-forge's `noarch`
  subdir, not `linux-64`; `micromamba` resolves both, so no special handling is
  needed beyond keeping `-c conda-forge`.
* `admixtools`'s `Suggests` are mostly Shiny/plotting extras that Strata does
  not use and are deliberately not installed. `admixturegraph` is not on
  conda-forge; it is only needed by `qpgraph` plotting helpers that Strata does
  not call.
* ADMIXTOOLS 2 declares `SystemRequirements: C++17, OpenMP`. `install_env.sh`
  pulls `gxx_linux-64` and `libgomp` from conda-forge for this; the Dockerfile
  uses the same toolchain in its build stage and discards it from the runtime
  image.
