"""Tool schema validity and tool implementations against the synthetic reference fixture."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from strata.agent.tools import (
    TOOLS,
    TOOLS_BY_NAME,
    ToolContext,
    execute_tool,
    tool_specs,
)


def test_every_tool_schema_is_valid_json_schema() -> None:
    validator = jsonschema.Draft202012Validator
    for tool in TOOLS:
        validator.check_schema(tool.input_schema)
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema.get("additionalProperties") is False, tool.name
        for req in schema.get("required", []):
            assert req in schema["properties"], f"{tool.name}: required {req} not in properties"


def test_tool_specs_are_json_serialisable_and_documented() -> None:
    specs = tool_specs()
    assert len(specs) == len(TOOLS)
    for spec in specs:
        json.dumps(spec.model_dump())
        assert len(spec.description) > 40, spec.name
    exploratory = {"nearest_populations", "fit_admixture", "rotate_sources",
                   "sensitivity_analysis"}
    for name in exploratory:
        assert "EXPLORATORY" in TOOLS_BY_NAME[name].description
    for name in ("run_qpadm", "run_qpadm_rotate", "run_f4"):
        assert "FORMAL" in TOOLS_BY_NAME[name].description


async def test_unknown_tool_and_bad_arguments_return_errors(tool_ctx: ToolContext) -> None:
    out = await execute_tool("no_such_tool", {}, tool_ctx)
    assert not out.ok and "unknown tool" in out.error

    out = await execute_tool("get_population", {}, tool_ctx)
    assert not out.ok and "invalid arguments" in out.error

    out = await execute_tool("search_populations", {"limit": 1000}, tool_ctx)
    assert not out.ok and "invalid arguments" in out.error

    out = await execute_tool("get_population", {"population_id": "x"}, tool_ctx,
                             parse_error="unterminated string")
    assert not out.ok and "INVALID_JSON" in out.error


async def test_search_and_get_population(tool_ctx: ToolContext) -> None:
    out = await execute_tool("search_populations", {"region": "South Asia"}, tool_ctx)
    assert out.ok
    ids = [p["id"] for p in out.result["populations"]]
    assert "Onge.SG" in ids and "Mbuti.DG" not in ids

    out = await execute_tool("get_population", {"population_id": "Onge.SG"}, tool_ctx)
    assert out.ok and out.result["population"]["n_samples"] == 5

    out = await execute_tool("get_population", {"population_id": "Nonexistent"}, tool_ctx)
    assert not out.ok and "not found" in out.error


async def test_list_user_datasets_omits_genotypes_and_pii(tool_ctx: ToolContext) -> None:
    out = await execute_tool("list_user_datasets", {}, tool_ctx)
    assert out.ok
    ds = out.result["datasets"][0]
    assert ds["id"] == "ds-1" and ds["qc"]["n_snps"] == 630000
    assert "genotypes" not in ds and "owner_email" not in ds
    assert "genotypes" not in out.content() and "example.com" not in out.content()


async def test_list_user_datasets_unavailable_is_tool_error(tool_ctx: ToolContext) -> None:
    ctx = ToolContext(user_id="u", reference=tool_ctx.reference, knowledge=tool_ctx.knowledge)
    out = await execute_tool("list_user_datasets", {}, ctx)
    assert not out.ok and "not available" in out.error


async def test_nearest_populations_is_labelled_exploratory(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "nearest_populations", {"target": {"dataset_id": "ds-1"}, "k": 3}, tool_ctx
    )
    assert out.ok
    assert out.result["kind"] == "exploratory"
    assert out.result["space"] == "g25"
    assert "caveat" in out.result
    neigh = out.result["neighbors"]
    assert len(neigh) == 3
    assert [n["distance"] for n in neigh] == sorted(n["distance"] for n in neigh)
    # Nearest to coordinate 0.75 should be the populations centred near 0.9 / 0.5.
    assert neigh[0]["name"] in {"Modern_Punjabi", "Iran_GanjDareh_N", "Tiny_Pop"}
    assert "result_id" in out.result


async def test_target_resolution_errors(tool_ctx: ToolContext) -> None:
    out = await execute_tool("nearest_populations", {"target": {}}, tool_ctx)
    assert not out.ok and "dataset_id or population" in out.error

    out = await execute_tool(
        "nearest_populations", {"target": {"population": "Nope"}}, tool_ctx
    )
    assert not out.ok and "no coordinates" in out.error

    out = await execute_tool(
        "nearest_populations", {"target": {"dataset_id": "ds-1"}, "space": "strata-pca-v1"},
        tool_ctx,
    )
    assert not out.ok  # fixture has no coordinates for that dataset/space combination


async def test_population_target_excludes_itself(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "nearest_populations", {"target": {"population": "Onge.SG"}, "k": 5}, tool_ctx
    )
    assert out.ok
    assert "Onge.SG" not in [n["name"] for n in out.result["neighbors"]]


async def test_fit_admixture_runs_real_analysis(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "fit_admixture",
        {
            "target": {"dataset_id": "ds-1"},
            "sources": ["Onge.SG", "Iran_GanjDareh_N", "Russia_Steppe_MLBA"],
        },
        tool_ctx,
    )
    assert out.ok, out.error
    assert out.result["kind"] == "exploratory"
    fit = out.result["fit"]
    assert fit["kind"] == "exploratory" and fit["caveat"]
    weights = {s["name"]: s["weight"] for s in fit["sources"]}
    assert set(weights) == {"Onge.SG", "Iran_GanjDareh_N", "Russia_Steppe_MLBA"}
    assert all(w >= -1e-9 for w in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert fit["distance"] >= 0.0


async def test_fit_admixture_bootstrap_needs_sample_coordinates(
    tool_ctx: ToolContext,
) -> None:
    """The fixture reference has no per-sample coordinates, so this must be a tool error."""
    out = await execute_tool(
        "fit_admixture",
        {
            "target": {"dataset_id": "ds-1"},
            "sources": ["Onge.SG", "Iran_GanjDareh_N"],
            "bootstrap": True,
        },
        tool_ctx,
    )
    assert not out.ok
    assert "per-sample coordinates" in out.error


async def test_rotate_and_sensitivity_run_real_analysis(tool_ctx: ToolContext) -> None:
    rot = await execute_tool(
        "rotate_sources",
        {
            "target": {"dataset_id": "ds-1"},
            "candidates": ["Onge.SG", "Iran_GanjDareh_N", "Russia_Steppe_MLBA", "Han.DG"],
            "k_max": 2,
        },
        tool_ctx,
    )
    assert rot.ok, rot.error
    models = rot.result["rotation"]["models"]
    assert models and [m["distance"] for m in models] == sorted(m["distance"] for m in models)

    sens = await execute_tool(
        "sensitivity_analysis",
        {
            "target": {"dataset_id": "ds-1"},
            "sources": ["Onge.SG", "Iran_GanjDareh_N", "Russia_Steppe_MLBA"],
        },
        tool_ctx,
    )
    assert sens.ok, sens.error
    assert sens.result["sensitivity"]["leave_one_source_out"]


async def test_rotate_sources_rejects_impossible_k(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "rotate_sources",
        {"target": {"dataset_id": "ds-1"}, "candidates": ["Onge.SG"], "k_min": 1, "k_max": 3},
        tool_ctx,
    )
    assert not out.ok and "k_max cannot exceed" in out.error


async def test_fit_admixture_rejects_unknown_sources(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "fit_admixture", {"target": {"dataset_id": "ds-1"}, "sources": ["Ghost_Pop"]}, tool_ctx
    )
    assert not out.ok and "unknown populations" in out.error


async def test_run_qpadm_requires_more_right_than_left(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "run_qpadm",
        {"target": "Modern_Punjabi", "sources": ["Onge.SG", "Han.DG"],
         "right": ["Mbuti.DG", "Iran_GanjDareh_N"]},
        tool_ctx,
    )
    assert not out.ok
    assert "more right than left" in out.error


async def test_run_qpadm_rejects_overlapping_sets(
    tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The spec's own validators reject a population on both sides."""
    monkeypatch.setenv("STRATA_F2_DIR", str(tmp_path / "f2"))

    async def run_job(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("must not reach the job runner")

    tool_ctx.run_job = run_job
    out = await execute_tool(
        "run_qpadm",
        {"target": "Modern_Punjabi", "sources": ["Onge.SG"],
         "right": ["Onge.SG", "Mbuti.DG", "Han.DG"]},
        tool_ctx,
    )
    assert not out.ok
    assert "both sides" in out.error


async def test_formal_tools_use_the_job_runner(
    tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # The f2 cache path is resolved server-side; point it at a stand-in directory.
    monkeypatch.setenv("STRATA_F2_DIR", str(tmp_path / "f2"))
    seen: list[tuple[str, dict[str, Any]]] = []

    async def run_job(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        seen.append((kind, payload))
        return {
            "kind": "formal",
            "target": "Modern_Punjabi",
            "weights": [
                {"left": "Onge.SG", "weight": 0.6, "se": 0.05, "z": 12.0},
                {"left": "Russia_Steppe_MLBA", "weight": 0.4, "se": 0.05, "z": 8.0},
            ],
            "p": 0.21,
            "chisq": 7.4,
            "dof": 6,
            "feasibility": {
                "verdict": "plausible",
                "reasons": ["p = 0.21 is above 0.05: not rejected"],
            },
        }

    tool_ctx.run_job = run_job
    out = await execute_tool(
        "run_qpadm",
        {"target": "Modern_Punjabi", "sources": ["Onge.SG", "Russia_Steppe_MLBA"],
         "right": ["Mbuti.DG", "Han.DG", "Iran_GanjDareh_N"]},
        tool_ctx,
    )
    assert out.ok, out.error
    assert out.result["kind"] == "formal"
    assert out.result["p"] == 0.21
    assert out.result["interpretation"] == ["p = 0.21 is above 0.05: not rejected"]
    kind, payload = seen[0]
    assert kind == "qpadm"
    assert payload["left"] == ["Onge.SG", "Russia_Steppe_MLBA"]
    assert payload["right"] == ["Mbuti.DG", "Han.DG", "Iran_GanjDareh_N"]
    assert payload["f2_dir"]  # resolved server-side, not supplied by the model


async def test_run_f4_validates_quadruples(tool_ctx: ToolContext) -> None:
    out = await execute_tool("run_f4", {"quadruples": [["A", "B", "C"]]}, tool_ctx)
    assert not out.ok  # schema requires exactly four entries


async def test_run_f4_zips_quadruples_rowwise(
    tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("STRATA_F2_DIR", str(tmp_path / "f2"))
    seen: dict[str, Any] = {}

    async def run_job(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        seen.update(payload)
        return {"f4": [], "n_statistics": 2}

    tool_ctx.run_job = run_job
    out = await execute_tool(
        "run_f4",
        {"quadruples": [["Mbuti.DG", "Han.DG", "Onge.SG", "Modern_Punjabi"],
                        ["Mbuti.DG", "Han.DG", "Onge.SG", "Iran_GanjDareh_N"]]},
        tool_ctx,
    )
    assert out.ok, out.error
    assert seen["comb"] is False
    assert seen["pop1"] == ["Mbuti.DG", "Mbuti.DG"]
    assert seen["pop4"] == ["Modern_Punjabi", "Iran_GanjDareh_N"]


async def test_formal_tools_report_unavailability_without_job_runner(
    tool_ctx: ToolContext,
) -> None:
    """With no worker and no local ADMIXTOOLS 2, the tool says so instead of guessing."""
    out = await execute_tool(
        "run_qpadm",
        {"target": "Modern_Punjabi", "sources": ["Onge.SG"],
         "right": ["Mbuti.DG", "Han.DG"]},
        tool_ctx,
    )
    if not out.ok:
        assert "unavailable" in out.error or "f2 cache" in out.error


async def test_compare_models_separates_exploratory_and_formal(tool_ctx: ToolContext) -> None:
    exp_id = tool_ctx.results.put(
        "fit_admixture",
        {"kind": "exploratory", "space": "g25", "target": "my-kit",
         "fit": {"sources": ["A", "B"], "weights": [0.7, 0.3], "distance": 0.031}},
    )
    exp2_id = tool_ctx.results.put(
        "fit_admixture",
        {"kind": "exploratory", "space": "g25", "target": "my-kit",
         "fit": {"sources": ["A", "C"], "weights": [0.5, 0.5], "distance": 0.012}},
    )
    formal_id = tool_ctx.results.put(
        "run_qpadm",
        {"kind": "formal", "weights": [{"left": "A", "weight": 0.6}, {"left": "B",
         "weight": 0.4}], "p": 0.3, "chisq": 5.0, "dof": 6,
         "feasibility": {"verdict": "plausible"}},
    )
    rejected_id = tool_ctx.results.put(
        "run_qpadm",
        {"kind": "formal", "weights": [{"left": "A", "weight": 1.2}, {"left": "B",
         "weight": -0.2}], "p": 0.001, "chisq": 30.0, "dof": 6,
         "feasibility": {"verdict": "infeasible"}},
    )
    out = await execute_tool(
        "compare_models", {"result_ids": [exp_id, exp2_id, formal_id, rejected_id]}, tool_ctx
    )
    assert out.ok
    exp_table = out.result["exploratory_table"]
    formal_table = out.result["formal_table"]
    assert len(exp_table) == 2 and len(formal_table) == 2
    # Separate tables; no shared ranking key across kinds.
    assert all(r["kind"] == "exploratory" for r in exp_table)
    assert all(r["kind"] == "formal" for r in formal_table)
    assert exp_table[0]["distance"] == 0.012  # ordered by distance
    assert formal_table[0]["not_rejected"] is True
    assert formal_table[1]["not_rejected"] is False
    assert "aic_like" in formal_table[0] and "aic_like" not in exp_table[0]
    assert any("never ranked together" in n for n in out.result["notes"])


async def test_compare_models_flags_mixed_spaces(tool_ctx: ToolContext) -> None:
    a = tool_ctx.results.put("fit_admixture", {"kind": "exploratory", "space": "g25",
                                               "fit": {"distance": 0.02}})
    b = tool_ctx.results.put("fit_admixture", {"kind": "exploratory", "space": "strata-pca-v1",
                                               "fit": {"distance": 0.01}})
    out = await execute_tool("compare_models", {"result_ids": [a, b]}, tool_ctx)
    assert out.ok
    assert any("different coordinate spaces" in n for n in out.result["notes"])


async def test_compare_models_rejects_unknown_result_ids(tool_ctx: ToolContext) -> None:
    out = await execute_tool("compare_models", {"result_ids": ["r999"]}, tool_ctx)
    assert not out.ok and "unknown result_ids" in out.error


async def test_retrieve_knowledge_returns_citable_chunks(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "retrieve_knowledge", {"query": "how should I interpret a qpAdm p-value", "k": 2},
        tool_ctx,
    )
    assert out.ok
    chunks = out.result["chunks"]
    assert chunks
    assert "interpreting-p-values" in chunks[0]["chunk_id"]
    assert all("chunk_id" in c and "text" in c for c in chunks)


async def test_propose_reference_sets_rationale_and_filters(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "propose_reference_sets",
        {
            "target": {"dataset_id": "ds-1"},
            "hypothesis": "three-way South Asian model",
            "n_sources": 4,
            "n_right": 4,
            "min_samples": 3,
            "right_anchors": ["Mbuti.DG"],
        },
        tool_ctx,
    )
    assert out.ok
    src_ids = [s["population"] for s in out.result["candidate_sources"]]
    right_ids = [r["population"] for r in out.result["right_populations"]]
    assert src_ids and right_ids
    # min_samples filter excludes the single-sample population.
    assert "Tiny_Pop" not in src_ids
    # Right set must not contain any candidate source.
    assert not (set(src_ids) & set(right_ids))
    assert "Mbuti.DG" in right_ids
    assert all(s["rationale"] for s in out.result["candidate_sources"])
    assert any("starting point" in r for r in out.result["rationale"])
    assert out.result["kind"] == "exploratory"


async def test_propose_reference_sets_respects_date_ordering(tool_ctx: ToolContext) -> None:
    """A source younger than the target is not proposed as a proximal source."""
    out = await execute_tool(
        "propose_reference_sets",
        {"target": {"population": "India_IVC_periphery"}, "target_date_bp": 4300,
         "n_sources": 6, "min_samples": 3},
        tool_ctx,
    )
    assert out.ok
    src_ids = [s["population"] for s in out.result["candidate_sources"]]
    assert "Russia_Steppe_MLBA" not in src_ids  # 3500 BP is younger than the 4300 BP target
    assert "Modern_Punjabi" not in src_ids


async def test_tool_result_json_has_no_nan(tool_ctx: ToolContext) -> None:
    out = await execute_tool(
        "nearest_populations", {"target": {"dataset_id": "ds-1"}, "k": 8}, tool_ctx
    )
    assert out.ok
    text = out.content()
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)


@pytest.mark.parametrize("name", [t.name for t in TOOLS])
def test_tool_names_are_snake_case(name: str) -> None:
    assert name == name.lower() and " " not in name
