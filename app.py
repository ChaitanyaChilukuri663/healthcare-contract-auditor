"""FastAPI entry point: health check + full audit pipeline with concurrency control.

On startup the audit pipeline is built if Azure is configured; otherwise the service
still starts and serves /health (audit returns 503). Heavy work is bounded by a
semaphore (CLAUDE.md: one heavy request at a time on small hosts).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pyodbc
from fastapi import FastAPI, HTTPException

from agents.llm_client import get_active_provider
from config import ConfigurationError, get_settings, get_version
from models import AuditRequest, AuditResponse, HealthResponse
from pipeline import AuditPipeline, build_default_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
_audit_semaphore = asyncio.Semaphore(settings.audit_concurrency)
_pipeline: AuditPipeline | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Build the pipeline on startup; tear down the DB pool on shutdown."""
    global _pipeline
    db = None
    try:
        _pipeline, db = await build_default_pipeline(settings)
        logger.info("Audit pipeline initialised")
    except (ConfigurationError, pyodbc.Error, OSError) as exc:
        logger.warning("Audit pipeline unavailable (serving health only): %s", exc)
        _pipeline = None
    try:
        yield
    finally:
        if db is not None:
            await db.close()
        _pipeline = None


app = FastAPI(
    title=settings.app_name,
    version=get_version(),
    summary="Audits healthcare provider contracts against CMS Medicare fee schedules.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe reporting the active LLM provider and the service version."""
    return HealthResponse(status="ok", provider=get_active_provider(), version=get_version())


@app.post("/audit_contract", response_model=AuditResponse)
async def audit_contract(request: AuditRequest) -> AuditResponse:
    """Run the 5-stage audit pipeline for a provider contract."""
    pipeline = _pipeline
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Audit pipeline is not configured (Azure settings missing).",
        )
    async with _audit_semaphore:
        logger.info(
            "audit_contract: npi=%s state=%s lob=%s contract=%s",
            request.provider_npi,
            request.state,
            request.lob,
            request.contract_id,
        )
        return await pipeline.run(request)
