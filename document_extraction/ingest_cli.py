"""CLI to ingest contract PDFs into Blob + AI Search and record them in meta_index.

Requires the AZURE_* values in .env (Blob, AI Search, SQL) and an LLM token for embeddings.

Examples (venv activated):
    python -m document_extraction.ingest_cli --demo
    python -m document_extraction.ingest_cli --pdf data/contracts/contract_provider_a.pdf \
        --npi 1234567890 --state TX --type contract --effective 2023-01-01
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from config import Settings, get_settings
from db.database import Database
from db.repository import DocumentRepository
from document_extraction.blob_store import BlobStore
from document_extraction.pdf_ingest import PdfIngestor
from document_extraction.search_index import SearchIndex
from models import DocumentType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestItem:
    """One PDF to ingest plus its provider metadata."""

    pdf: Path
    provider_npi: str
    state: str
    doc_type: DocumentType
    effective_date: date | None


# The bundled synthetic contracts (see data/README.md).
DEMO_ITEMS: list[IngestItem] = [
    IngestItem(
        Path("data/contracts/contract_provider_a.pdf"),
        "1234567890",
        "TX",
        DocumentType.CONTRACT,
        date(2023, 1, 1),
    ),
    IngestItem(
        Path("data/contracts/amendment_provider_a.pdf"),
        "1234567890",
        "TX",
        DocumentType.AMENDMENT,
        date(2024, 1, 1),
    ),
    IngestItem(
        Path("data/contracts/contract_provider_b.pdf"),
        "1987654321",
        "NY",
        DocumentType.CONTRACT,
        date(2022, 3, 1),
    ),
]


def _build_components(settings: Settings) -> tuple[PdfIngestor, Database, DocumentRepository]:
    if not settings.azure_search_endpoint or not settings.azure_search_key:
        raise SystemExit("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env")
    blob = BlobStore(
        container=settings.blob_container,
        connection_string=settings.azure_blob_connection_string,
        account_url=settings.azure_blob_account_url,
    )
    search = SearchIndex(
        endpoint=settings.azure_search_endpoint,
        key=settings.azure_search_key,
        index_name=settings.azure_search_index,
        dimensions=settings.embedding_dimensions,
    )
    db = Database(settings.sql_connection_string())
    return PdfIngestor(settings, blob, search), db, DocumentRepository(db)


async def ingest_items(items: list[IngestItem]) -> None:
    """Ingest each item and record it in app_config.meta_index."""
    settings = get_settings()
    ingestor, db, documents = _build_components(settings)
    await db.connect()
    try:
        for item in items:
            data = item.pdf.read_bytes()
            meta = await ingestor.ingest(
                provider_npi=item.provider_npi,
                state=item.state,
                doc_type=item.doc_type,
                filename=item.pdf.name,
                data=data,
                effective_date=item.effective_date,
            )
            await documents.upsert(meta)
            logger.info("Ingested %s -> doc_id=%s", item.pdf.name, meta.doc_id)
    finally:
        await db.close()


def _parse_args(argv: list[str] | None = None) -> list[IngestItem]:
    parser = argparse.ArgumentParser(description="Ingest contract PDFs into Blob + AI Search.")
    parser.add_argument("--demo", action="store_true", help="Ingest the bundled synthetic PDFs.")
    parser.add_argument("--pdf", type=Path, help="Path to a single PDF to ingest.")
    parser.add_argument("--npi", help="Provider NPI.")
    parser.add_argument("--state", help="Two-letter state code, e.g. TX.")
    parser.add_argument(
        "--type", choices=[t.value for t in DocumentType], default=DocumentType.CONTRACT.value
    )
    parser.add_argument("--effective", help="Effective date (YYYY-MM-DD).")
    args = parser.parse_args(argv)

    if args.demo:
        return DEMO_ITEMS
    if not (args.pdf and args.npi and args.state):
        parser.error("provide --demo, or --pdf with --npi and --state")
    effective = date.fromisoformat(args.effective) if args.effective else None
    return [IngestItem(args.pdf, args.npi, args.state, DocumentType(args.type), effective)]


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ingest_items(_parse_args(argv)))


if __name__ == "__main__":
    main()
