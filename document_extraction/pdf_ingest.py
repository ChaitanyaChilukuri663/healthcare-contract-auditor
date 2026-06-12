"""Stage 2: ingest contract PDFs into Blob Storage and the AI Search vector index.

Pipeline: PDF bytes -> Blob upload -> text extraction -> chunking -> embeddings
(via the provider abstraction) -> AI Search upload. Returns a DocumentMeta for the
caller to persist in app_config.meta_index.
"""

import hashlib
import io
import logging
import uuid
from datetime import date

from pypdf import PdfReader

from agents import llm_client
from config import Settings
from document_extraction.blob_store import BlobStore
from document_extraction.search_index import SearchIndex
from models import DocumentChunk, DocumentMeta, DocumentType

logger = logging.getLogger(__name__)


def sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes (document cache-key component)."""
    return hashlib.sha256(data).hexdigest()


def extract_pages(data: bytes) -> list[str]:
    """Extract text per page from a PDF."""
    reader = PdfReader(io.BytesIO(data))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split text into overlapping windows (character-based, deterministic, offline)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    step = max(1, max_chars - overlap_chars)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + max_chars].strip()
        if piece:
            chunks.append(piece)
    return chunks


class PdfIngestor:
    """Ingests a single PDF into Blob + AI Search."""

    def __init__(
        self, settings: Settings, blob_store: BlobStore, search_index: SearchIndex
    ) -> None:
        self._settings = settings
        self._blob = blob_store
        self._search = search_index

    def _max_chars(self) -> int:
        # ~4 characters per token is a reasonable heuristic for English prose.
        return self._settings.chunk_max_tokens * 4

    def _overlap_chars(self) -> int:
        return self._settings.chunk_overlap_tokens * 4

    def build_chunks(
        self, *, doc_id: str, provider_npi: str, state: str, pages: list[str]
    ) -> list[DocumentChunk]:
        """Turn extracted pages into chunk records (without embeddings yet)."""
        chunks: list[DocumentChunk] = []
        for page_number, page_text in enumerate(pages, start=1):
            for piece in chunk_text(page_text, self._max_chars(), self._overlap_chars()):
                chunks.append(
                    DocumentChunk(
                        chunk_id=uuid.uuid4().hex,
                        doc_id=doc_id,
                        provider_npi=provider_npi,
                        state=state,
                        content=piece,
                        page=page_number,
                    )
                )
        return chunks

    async def ingest(
        self,
        *,
        provider_npi: str,
        state: str,
        doc_type: DocumentType,
        filename: str,
        data: bytes,
        effective_date: date | None = None,
    ) -> DocumentMeta:
        """Ingest one PDF end-to-end and return its metadata."""
        doc_hash = sha256_hex(data)
        doc_id = uuid.uuid4().hex
        blob_name = f"{provider_npi}/{doc_id}/{filename}"
        blob_path = await self._blob.upload_pdf(blob_name, data)

        pages = extract_pages(data)
        chunks = self.build_chunks(
            doc_id=doc_id, provider_npi=provider_npi, state=state, pages=pages
        )
        if chunks:
            vectors = await llm_client.embed([chunk.content for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=False):
                chunk.embedding = vector
            await self._search.ensure_index()
            await self._search.upload_chunks(chunks)

        logger.info(
            "Ingested doc %s for provider %s (%d chunks)", doc_id, provider_npi, len(chunks)
        )
        return DocumentMeta(
            doc_id=doc_id,
            provider_npi=provider_npi,
            state=state,
            doc_type=doc_type,
            blob_path=blob_path,
            doc_hash=doc_hash,
            effective_date=effective_date,
        )
