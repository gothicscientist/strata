# Roadblocks

What is standing between Strata as it is now and Strata fully working, with the
fix for each. Written 2026-11-01, after the platform (PR #1) merged and the
AADR v66.p1 reference build (PR #2) came up for review.

Three kinds of entry:

* **Fixed here** — the fix is in this branch.
* **Needs you** — nothing in the code can resolve it; it needs an action or a
  decision from Bharat.
* **Open** — known, scoped, not yet done.

---

## 1. The reference library was not on `main` — *resolved 2026-11-01*

[PR #2](https://github.com/gothicscientist/strata/pull/2) is merged, so `main`
now carries the AADR-derived reference library: 188 populations, 3,332 samples
and the `strata-pca-v1` coordinates, built end to end against AADR v66.p1. The
library and PCA pages no longer fall back to their "not built yet" notice.

The f2 cache is a separate matter — it is not committed, and item 5 is what
makes it obtainable.

---

## 2. The panel report could not tell a rename from a missing group — *fixed here*

AADR relabelled its whole compendium in v66.p1, and the panel deliberately
carries labels from several releases so older ones keep resolving. Resolution
reported every label that matched nothing in one list, so the build reported
**137 unmatched labels** — a number that looks alarming and cannot be acted on,
because most of those labels are ones the release renamed and nothing was lost.

`panel.py` now classifies each miss. A miss is a *rename* when the release
carries the same individuals under another label — either a sequencing-source
alias whose bare form resolved (`Mbuti.DG` where `Mbuti` exists), or an
explicit entry in the new `RELABELLED` map read off the v66.p1 `.ind` files.
Everything else is a real gap. On v66.p1:

| | labels |
|---|---|
| renamed, replacement resolved | 96 |
| absent from the release | **41** |

`MANIFEST.json` → `panel` now records `superseded_labels`, `missing_labels` and
their counts, and the build's warning names only the 41. `RELABELLED` is
covered by a test that every replacement is a label the panel actually asks
for, so an entry cannot quietly turn a real gap into a reported rename.

---

## 3. A missing outgroup was reported nowhere — *fixed here*

Two related holes in `resolve()`:

* The right set is applied to every panel, and a right label that matched
  nothing was **dropped silently**. So a release missing a standing outgroup
  reported a complete panel. That is the one miss that matters most: a missing
  right population changes what the statistics can resolve, not just what is
  listed.
* A conventional outgroup is usually also a panel member — `Mbuti` and `Papuan`
  sit in `modern_global` — and the panel block wins the role, so `roles` shows
  only 7 populations as `right`. Anything reading `roles` to assemble an
  outgroup set would get a set of seven low-coverage ancient genomes with no
  African, Papuan, East Asian or American outgroup in it.

Right-set misses are now reported (in their own field, so a caller's own panel
does not look as if it had asked for the outgroups), and the manifest records
`panel.right_set` — every group the standing right set resolved to, whatever
role it ended up with.

Nothing in the API or the agent reads `role == "right"` today: a right set is
always supplied by the caller. Exposing `panel.right_set` through the reference
API, so the agent proposes a curated outgroup set instead of inventing one, is
worth doing next and is item 7 below.

---

## 4. No present-day Andamanese group in the public release — *decided; in progress*

Bharat chose, on 2026-11-01, to rework the panel around what v66.p1 ships and
then add the 1000 Genomes South Asian panels (option 2 below). The rework is
done; the second source is item 11.

Of the 41 labels genuinely absent from v66.p1, 39 are present-day South Asian
groups, and they include all three Andamanese labels (`Onge`, `Jarawa`,
`Great_Andamanese`). Those are the conventional proxy for the deep indigenous
South Asian component, and the panel was designed with `Onge` in both the
source role and the standing right set. Their absence is why the Swat Iron Age
model the data thread ran came back rejected (p = 0.005, steppe weight
0.019 ± 0.050, i.e. not determined): the right set has no population that is
specifically informative about that component, so the model is
under-identified. The engine is working; the panel is missing a leg.

Worth correcting one thing from the earlier write-up, though — the gap is
narrower than it looked. v66.p1 **does** ship present-day South Asian groups:
25 populations, 434 individuals in the `modern_south_asia` block, of which 10
are Indian groups (`Irula`, `Mala`, `Madiga`, `Kapu`, `Khonda_Dora`, `Relli_1`,
`Relli_2`, `Brahmin`, `Yadava`, plus `Sherpa` and `Tharu` from Nepal) alongside
the four Gujarati panels and nine Pakistani groups. Several of those are
exactly the groups the literature uses at the indigenous-ancestry-rich end of
the Indian cline. So exploratory work — PCA placement, distances, admixture
fitting for a user's own coordinates — has real coverage across the cline
today. What is missing is specifically an Andamanese-related *outgroup*, and
that constrains formal qpAdm, not the rest of the platform.

The missing groups are not an oversight in the release: AADR publishes only
what its sample consents allow to be redistributed, which is why the Reich-lab
Indian and Andamanese panels are not in it. No rebuild will produce them.

Three ways forward, in the order I would take them:

1. **Rework the panel around what v66.p1 ships, and scope the formal claims to
   match.** Drop the 39 phantom South Asian labels, keep the indigenous-rich
   Indian groups that do resolve as the cline anchors, keep `Papuan` as the
   only deep Australasian-related outgroup, and have the UI and the agent say
   plainly that models involving the deep indigenous component are
   under-identified in this panel. A day of work, no new data source, and
   every number stays real. **This is what I recommend.**
2. **Add the 1000 Genomes South Asian panels** (Gujarati, Punjabi, Bengali,
   Tamil, Telugu) as a second reference source. They are fully public, large,
   and would widen present-day coverage well beyond AADR's handful of samples
   per group — good for the exploratory side and for users with Indian
   ancestry. It does not fix the outgroup problem. Roughly two to three days:
   a second downloader, harmonisation onto the 1240K panel, and provenance.
   Blocked in some containers (`ftp.1000genomes.ebi.ac.uk`), so it would run on
   a GitHub runner.
3. **Hunt for a redistributable Andamanese genotype source first.** The SGDP
   samples behind AADR's old `Onge.DG` label are restricted for the same
   consent reason, so I would expect this to come back empty, and I would not
   spend the time before 1 and 2 are done.

**What the rework changed.** The 39 labels the public AADR cannot carry are now
recorded in `UNAVAILABLE_IN_PUBLIC_AADR` with the reason — `consent` for the
Reich-lab Indian and Andamanese panels, `in_1000_genomes` for the three the
1000 Genomes Project publishes instead — so they are reported as understood
rather than as something to chase, and the build's warning is left naming only
the two labels that are absent for no recorded reason (`Tuscan`,
`Russia_Samara_HG*`), which is the list worth looking at after a version bump.

What the gap *costs* is now computed rather than left in prose. `panel_limits()`
checks whether any Andamanese-related label resolved and, when none did, emits a
`no_aasi_proxy` limit naming the analyses it affects. The manifest carries it,
`/api/v1/reference/panel` serves it, `/health` states it in its notes, every
formal agent result carries it, and the formal result view prints it above the
numbers. The check is against the release, so the limit disappears by itself
once any source supplies a proxy — including the 1000 Genomes work in item 11.

---

## 5. A fresh clone could not run a formal model — *resolved 2026-11-01*

The f2 block cache is the only reference artefact that is neither committed nor
cheap: 147 MB, gitignored, and about 45 minutes plus the full 11 GB AADR
download and an ADMIXTOOLS 2 install to rebuild. Every clone — including every
deployment — therefore started with no cache, and every formal analysis failed
until someone ran the whole pipeline. The build workflow already published the
cache as a release asset; nothing consumed it.

`make fetch-f2` (`python -m pipeline fetch-f2`) is the consumer side. It needs
`github.com` and nothing else: no Dataverse, no R. It

* verifies the tarball against the `.sha256` published beside it;
* refuses any archive member that would write outside the destination, or any
  link or special file, because the archive is untrusted network input;
* refuses a cache whose population count disagrees with the committed
  `MANIFEST.json`, since a cache fixes the SNP set for every statistic computed
  from it — the wrong cache would shift p-values rather than fail;
* unpacks to a staging directory and swaps, so a failure part-way cannot leave
  a half-extracted cache that later looks usable;
* leaves an existing cache alone unless `--force`.

`REPO=` and `TAG=` point it at a fork or an internal mirror.

**Done.** Bharat asked for the build to be run on 2026-11-01; the
[`reference-strata-ref-v1`](https://github.com/gothicscientist/strata/releases/tag/reference-strata-ref-v1)
release now carries `f2-strata-ref-v1.tar.gz` and its `.sha256`. Verified from
this container against the published asset: 9 seconds and 136 populations,
against ~45 minutes plus an 11 GB download and an ADMIXTOOLS 2 install to
rebuild. Re-run the workflow after any change that alters the SNP set or the
population list, because the committed `MANIFEST.json` is what `fetch-f2`
checks the cache against and a mismatch is refused.

---

## 6. The AI research agent has no credentials — *needs you*

The agent is complete: 13 tools, Claude and OpenAI providers, retrieval over
the methods corpus, and a grounding check that flags numbers in an answer that
appear in no tool result. It stays switched off until a key is present, and
`llm_available()` reports only whether credentials exist, never their values.

**Fix:** set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) in the API and worker
environment. `/api/v1/health` then reports the provider as available. Nothing
in the repository needs changing.

---

## 7. No canonical outgroup set was exposed to the agent or the UI — *fixed here*

Following from item 3: a right set is always supplied by the caller, so the
agent assembles one itself for every formal model. It has no curated default to
start from, which puts the quality of a formal model at the mercy of the
model's own choice of outgroups.

**Fixed with the rework.** `/api/v1/reference/panel` serves `right_set`, and the
agent has a `describe_reference_panel` tool whose description tells it to start
a right set there rather than choose outgroups itself. The tool reports the
panel as undescribed rather than returning an empty one, because an empty panel
reads as a panel with no limits.

Still open: the qpAdm tools do not *default* `right` to that set when the model
omits it, and the formal-model UI shows the right set in use but not that it
came from the panel. Both are small, and neither is load-bearing now that the
set is one tool call away.

---

## 8. Nothing is deployed — *needs you*

`docs/DEPLOYMENT.md` covers it end to end, and `infra/` has the container and
Pages configuration, but no environment exists: no Supabase project, no
Cloudflare Pages site, no container host for the API and worker. These need
accounts and credentials I do not have.

**Fix:** decide where it should live. If you want it public for a recruiter to
click, the cheapest shape is Supabase free tier, Cloudflare Pages for the
frontend, and one small container host for the API and the worker, with
`make fetch-f2` run in the image build so the reference data is baked in.
Tell me the target and I will do the configuration and the first deploy.

---

## 9. Container network access varies between sessions — *mitigated*

Harvard Dataverse was blocked in one session's container and served the full
11 GB download in another, and `cloud.r-project.org` has been blocked in both.
Nothing in the project controls this. It is mitigated rather than fixed:

* the build runs on a GitHub runner via `build-reference.yml` when a container
  cannot reach Dataverse;
* ADMIXTOOLS 2 installs from conda-forge via
  `services/worker/r/install_env.sh`, not CRAN;
* and `make fetch-f2` now needs only `github.com`, so a container that can
  reach neither Dataverse nor CRAN can still get a working reference library.

---

## 10. The f2 coverage floor costs 35 populations — *accepted, documented*

With `maxmiss = 0` a SNP survives only where every population has an
observation, so one sparse individual in a single-individual population deletes
every SNP it is missing: the curated panel shares **zero** autosomal SNPs with
no coverage floor. The pinned 800,000-SNP per-individual floor yields 228,853
SNPs across 136 populations, at the cost of the 35 sparsest populations, which
remain in `samples.parquet` and in the PCA.

The alternative — relaxing `maxmiss` — would let different statistics rest on
different SNP sets, which is worse: it makes two models silently
non-comparable. The floor is in the pinned config and recorded in the manifest.
Worth revisiting only if a specific analysis needs one of the dropped
populations, and then as a second, separately identified cache rather than a
change to this one.

---

## 11. Present-day South Asian coverage is thin — *fixed here*

Following the item 4 decision. The 25 South Asian populations v66.p1 ships
total 434 individuals, and the Indian groups among them have one or two
samples each — enough to place a population mean on the PCA, thin for anything
that needs within-population variation, and nothing like the coverage a user
with Indian ancestry would expect to be compared against.

The 1000 Genomes Project publishes five South Asian panels with roughly a
hundred samples each and no consent restriction: Gujarati (GIH), Punjabi
(PJL), Bengali (BEB), Sri Lankan Tamil (STU) and Indian Telugu (ITU). Three of
those are labels this panel already asks for and AADR does not carry, which is
why they are marked `in_1000_genomes` rather than `consent`.

It does not supply an Andamanese-related outgroup, so the `no_aasi_proxy` limit
stands either way; what it changes is the exploratory side — PCA placement,
distances and admixture fitting against groups with real sample counts.

**Built.** `make onekg` (`python -m pipeline onekg`) streams each autosome's
phase 3 VCF from EBI, keeps only the positions in the committed SNP panel, and
writes the five populations on the same SNP set and allele orientation as
everything else — 489 individuals, group IDs suffixed `_1000G` so they are
never pooled with an AADR group of the same name. It then projects them into
`strata-pca-v1` and appends the populations, samples and coordinates to the
derived tables.

Three things it is careful about, each of which is a way to get plausible
numbers that are wrong:

* **Allele orientation is checked per site**, never assumed. A site is kept only
  when the VCF's REF/ALT pair is the panel's pair, in either order, or its
  unambiguous strand complement. An A/T or C/G site that does not match
  directly is dropped rather than resolved by guess, which would invert every
  genotype at that site. The flip count is reported so a disagreement between
  panel and callset is visible instead of silent.
* **Positions are never matched across builds.** Phase 3 is GRCh37, the panel's
  build; the extractor refuses a panel on any other.
* **The coordinates are projected, not fitted.** A present-day cohort of ~500
  added to the fit would dominate the axes and move every existing coordinate,
  so these rows are projected and marked `projected`, like the ancient
  individuals.

`ftp.1000genomes.ebi.ac.uk` turned out to be reachable from this container, so
the extraction ran here for real rather than only on a runner. chr22 alone:
1,103,547 VCF sites scanned in 35 seconds, 5,797 of the panel's 5,798 chr22
positions kept, no allele mismatches and no strand flips — which is itself
evidence that the panel and the callset agree on orientation. The workflow
gained an `include_1000_genomes` input for the full run.

It does not supply an Andamanese-related outgroup, so `no_aasi_proxy` still
applies; the gain is on the exploratory side.

---

## 12. The build workflow cannot open its own pull request — *needs you, one checkbox*

The 2026-11-01 run did everything asked of it — downloaded v66.p1, curated,
fitted the PCA space, built the f2 cache and published the release — and then
failed on its last step:

```
GitHub Actions is not permitted to create or approve pull requests.
```

That is a repository setting, not a bug in the workflow. The derived files were
not lost: they are pushed to the branch
`reference/strata-ref-v1-v66.p1`, so a PR can be opened from it by hand.

**Fix:** in **Settings → Actions → General → Workflow permissions**, tick
*Allow GitHub Actions to create and approve pull requests*. One checkbox, and
every later run opens its own PR instead of stopping one step short. Until it is
ticked, run the workflow with `open_pull_request=false` and open the PR from the
pushed branch yourself.
