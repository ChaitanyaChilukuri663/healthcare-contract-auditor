"""Typed repositories over the facets_sim and app_config schemas.

Every query is parameterized. Repositories return Pydantic models or plain values,
never raw rows (CLAUDE.md: public functions return Pydantic models, not dicts).
"""

import logging
from typing import Any

from db.database import Database
from models import (
    AuditReport,
    DocumentMeta,
    DocumentType,
    ProviderAgreement,
)

logger = logging.getLogger(__name__)


class ProviderAgreementRepository:
    """facets_sim.provider_agreement."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(
        self, provider_npi: str, contract_id: str, state: str
    ) -> ProviderAgreement | None:
        row = await self._db.fetch_one(
            """
            SELECT provider_npi, contract_id, state, lob, effective_date, terminate_date
            FROM facets_sim.provider_agreement
            WHERE provider_npi = ? AND contract_id = ? AND state = ?
            """,
            (provider_npi, contract_id, state),
        )
        return _to_agreement(row) if row else None

    async def list_all(self) -> list[ProviderAgreement]:
        rows = await self._db.fetch_all(
            """
            SELECT provider_npi, contract_id, state, lob, effective_date, terminate_date
            FROM facets_sim.provider_agreement
            ORDER BY provider_npi, contract_id
            """
        )
        return [_to_agreement(row) for row in rows]


class DocumentRepository:
    """app_config.meta_index."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_for(self, provider_npi: str, state: str) -> list[DocumentMeta]:
        rows = await self._db.fetch_all(
            """
            SELECT doc_id, provider_npi, state, doc_type, blob_path, doc_hash,
                   effective_date, uploaded_at
            FROM app_config.meta_index
            WHERE provider_npi = ? AND state = ?
            ORDER BY effective_date
            """,
            (provider_npi, state),
        )
        return [_to_document_meta(row) for row in rows]

    async def upsert(self, meta: DocumentMeta) -> None:
        await self._db.execute(
            """
            MERGE app_config.meta_index AS target
            USING (SELECT ? AS doc_id) AS source ON target.doc_id = source.doc_id
            WHEN MATCHED THEN UPDATE SET
                provider_npi = ?, state = ?, doc_type = ?, blob_path = ?,
                doc_hash = ?, effective_date = ?
            WHEN NOT MATCHED THEN INSERT
                (doc_id, provider_npi, state, doc_type, blob_path, doc_hash, effective_date)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                meta.doc_id,
                meta.provider_npi,
                meta.state,
                meta.doc_type.value,
                meta.blob_path,
                meta.doc_hash,
                meta.effective_date,
                meta.doc_id,
                meta.provider_npi,
                meta.state,
                meta.doc_type.value,
                meta.blob_path,
                meta.doc_hash,
                meta.effective_date,
            ),
        )


class DocCacheRepository:
    """app_config.doc_cache — keyed on (doc_hash, prompt_hash, provider)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, doc_hash: str, prompt_hash: str, provider: str) -> str | None:
        row = await self._db.fetch_one(
            """
            SELECT response_json FROM app_config.doc_cache
            WHERE doc_hash = ? AND prompt_hash = ? AND provider = ?
            """,
            (doc_hash, prompt_hash, provider),
        )
        return str(row["response_json"]) if row else None

    async def put(self, doc_hash: str, prompt_hash: str, provider: str, response_json: str) -> None:
        await self._db.execute(
            """
            MERGE app_config.doc_cache AS target
            USING (SELECT ? AS doc_hash, ? AS prompt_hash, ? AS provider) AS source
                ON target.doc_hash = source.doc_hash
               AND target.prompt_hash = source.prompt_hash
               AND target.provider = source.provider
            WHEN MATCHED THEN UPDATE SET response_json = ?
            WHEN NOT MATCHED THEN INSERT (doc_hash, prompt_hash, provider, response_json)
                VALUES (?, ?, ?, ?);
            """,
            (
                doc_hash,
                prompt_hash,
                provider,
                response_json,
                doc_hash,
                prompt_hash,
                provider,
                response_json,
            ),
        )


class PromptRepository:
    """app_config.prompt_registry — DB-driven, hot-reloadable prompts."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, name: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT prompt_text FROM app_config.prompt_registry WHERE name = ?",
            (name,),
        )
        return str(row["prompt_text"]) if row else None


class FacetsRepository:
    """facets_sim benchmark/ground-truth lookups for the strict grader."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def filing_benchmark(self, state: str, lob: str) -> int | None:
        row = await self._db.fetch_one(
            "SELECT days_to_file FROM facets_sim.filing_rule WHERE state = ? AND lob = ?",
            (state, lob),
        )
        return int(row["days_to_file"]) if row else None

    async def reimbursement_policy(self, state: str, lob: str) -> dict[str, Any] | None:
        return await self._db.fetch_one(
            """
            SELECT lesser_of_required, expected_pct_of_medicare
            FROM facets_sim.reimbursement_policy
            WHERE state = ? AND lob = ?
            """,
            (state, lob),
        )

    async def mpfs_amount(self, cpt_code: str, locality: str) -> float | None:
        row = await self._db.fetch_one(
            "SELECT amount FROM facets_sim.mpfs_fee WHERE cpt_code = ? AND locality = ?",
            (cpt_code, locality),
        )
        return float(row["amount"]) if row else None


class AuditRunRepository:
    """app_config.audit_runs — audit history."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, report: AuditReport) -> None:
        case_type = report.case_type.value if report.case_type else None
        await self._db.execute(
            """
            INSERT INTO app_config.audit_runs
                (contract_id, provider_npi, state, lob, case_type, outcome,
                 checks_total, checks_failed, report_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.contract_id,
                report.provider_npi,
                report.state,
                report.lob,
                case_type,
                report.outcome.value,
                report.checks_total,
                report.checks_failed,
                report.model_dump_json(),
                report.generated_at,
            ),
        )


# --------------------------------------------------------------------------- #
# Row -> model helpers                                                        #
# --------------------------------------------------------------------------- #


def _to_agreement(row: dict[str, Any]) -> ProviderAgreement:
    return ProviderAgreement(
        provider_npi=str(row["provider_npi"]),
        contract_id=str(row["contract_id"]),
        state=str(row["state"]),
        lob=str(row["lob"]),
        effective_date=row["effective_date"],
        terminate_date=row["terminate_date"],
    )


def _to_document_meta(row: dict[str, Any]) -> DocumentMeta:
    return DocumentMeta(
        doc_id=str(row["doc_id"]),
        provider_npi=str(row["provider_npi"]),
        state=str(row["state"]),
        doc_type=DocumentType(row["doc_type"]),
        blob_path=str(row["blob_path"]),
        doc_hash=str(row["doc_hash"]),
        effective_date=row.get("effective_date"),
        uploaded_at=row["uploaded_at"],
    )
