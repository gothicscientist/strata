from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from strata import __version__
from strata.api import science
from strata.api.deps import DbDep, SettingsDep
from strata.api.examples_store import list_examples
from strata.api.schemas import Capabilities, Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, summary="Liveness and capability flags")
def health(db: DbDep, settings: SettingsDep) -> Health:
    """Reports what this deployment can actually do. Flags are computed, never assumed:
    `qpadm` is true only if R + ADMIXTOOLS 2 respond, `reference_loaded` only if the reference
    artefacts load, `llm_providers` lists providers with a configured key."""
    notes: list[str] = []
    db_ok = True
    try:
        db.execute(text("select 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
        notes.append("database unreachable")
    lib = science.try_reference_library()
    panel = science.snp_panel() if lib is not None else None
    qpadm = science.qpadm_available()
    providers = science.llm_providers()
    if lib is None:
        notes.append("reference library not loaded: analyses against reference populations "
                     "are unavailable (build data/derived with the data pipeline)")
    if not qpadm:
        notes.append("qpAdm unavailable: formal f-statistics tests need R + ADMIXTOOLS 2 "
                     "(services/worker image)")
    if not settings.llm_configured:
        notes.append(f"research assistant disabled: no API key for {settings.llm_provider}")
    if not settings.data_key:
        notes.append("STRATA_DATA_KEY not set: using an ephemeral dev key (data lost on restart)")
    from strata.jobs.registry import kinds

    pca_space = science.default_pca_space()
    caps = Capabilities(
        qpadm=qpadm, llm_providers=providers, llm_configured=settings.llm_configured,
        reference_version=science.reference_version(), reference_loaded=lib is not None,
        snp_panel_loaded=panel is not None, pca_space=pca_space, job_mode=settings.job_mode,
        job_kinds=kinds(), storage_backend=settings.storage_backend,
        database="postgres" if settings.is_postgres else "sqlite",
        auth={"guest": True, "supabase_hs256": bool(settings.supabase_jwt_secret),
              "supabase_jwks": bool(settings.supabase_jwks_url or settings.supabase_url)},
        examples=len(list_examples(settings.examples_dir)),
    )
    return Health(status="ok" if db_ok else "degraded", version=__version__,
                  capabilities=caps, notes=notes)
