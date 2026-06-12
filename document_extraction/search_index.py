"""Azure AI Search wrapper: vector index lifecycle, upload, and retrieval.

Shared by ingestion (writes chunks) and the RAG agent (reads chunks).
"""

import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.indexes.models import (
    SearchIndex as AzureSearchIndex,
)
from azure.search.documents.models import VectorizedQuery

from models import DocumentChunk, RetrievedChunk

logger = logging.getLogger(__name__)

_VECTOR_PROFILE = "vprofile"
_HNSW_CONFIG = "hnsw"

# Edm type names (passed as strings to avoid azure-sdk enum/pyright typing friction).
_EDM_STRING = "Edm.String"
_EDM_INT32 = "Edm.Int32"
_EDM_SINGLE_COLLECTION = "Collection(Edm.Single)"


class SearchIndex:
    """Manages and queries the contract-chunk vector index in Azure AI Search."""

    def __init__(self, endpoint: str, key: str, index_name: str, dimensions: int) -> None:
        self._endpoint = endpoint
        self._credential = AzureKeyCredential(key)
        self._index_name = index_name
        self._dimensions = dimensions

    async def ensure_index(self) -> None:
        """Create or update the vector index."""
        fields = [
            SimpleField(name="chunk_id", type=_EDM_STRING, key=True),
            SimpleField(name="doc_id", type=_EDM_STRING, filterable=True),
            SimpleField(name="provider_npi", type=_EDM_STRING, filterable=True),
            SimpleField(name="state", type=_EDM_STRING, filterable=True),
            SimpleField(name="page", type=_EDM_INT32),
            SearchableField(name="content", type=_EDM_STRING),
            SearchField(
                name="embedding",
                type=_EDM_SINGLE_COLLECTION,
                searchable=True,
                vector_search_dimensions=self._dimensions,
                vector_search_profile_name=_VECTOR_PROFILE,
            ),
        ]
        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name=_HNSW_CONFIG)],
            profiles=[
                VectorSearchProfile(name=_VECTOR_PROFILE, algorithm_configuration_name=_HNSW_CONFIG)
            ],
        )
        index = AzureSearchIndex(name=self._index_name, fields=fields, vector_search=vector_search)
        async with SearchIndexClient(self._endpoint, self._credential) as client:
            await client.create_or_update_index(index)
            logger.info("Ensured AI Search index %s", self._index_name)

    async def upload_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Upload chunk documents (each must carry an embedding)."""
        if not chunks:
            return
        documents = [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "provider_npi": chunk.provider_npi,
                "state": chunk.state,
                "page": chunk.page,
                "content": chunk.content,
                "embedding": chunk.embedding,
            }
            for chunk in chunks
        ]
        async with SearchClient(self._endpoint, self._index_name, self._credential) as client:
            await client.upload_documents(documents=documents)
            logger.info("Uploaded %d chunks to %s", len(documents), self._index_name)

    async def search(
        self,
        query_vector: list[float],
        *,
        provider_npi: str | None = None,
        state: str | None = None,
        top: int = 5,
    ) -> list[RetrievedChunk]:
        """Vector-search the index, optionally filtered by provider/state."""
        filters: list[str] = []
        if provider_npi:
            filters.append(f"provider_npi eq '{provider_npi}'")
        if state:
            filters.append(f"state eq '{state}'")
        filter_expr = " and ".join(filters) if filters else None

        vector_query = VectorizedQuery(
            vector=query_vector, k_nearest_neighbors=top, fields="embedding"
        )
        async with SearchClient(self._endpoint, self._index_name, self._credential) as client:
            results = await client.search(
                search_text=None, vector_queries=[vector_query], filter=filter_expr, top=top
            )
            retrieved: list[RetrievedChunk] = []
            async for doc in results:
                retrieved.append(
                    RetrievedChunk(
                        chunk_id=str(doc["chunk_id"]),
                        doc_id=str(doc["doc_id"]),
                        content=str(doc["content"]),
                        score=float(doc.get("@search.score", 0.0)),
                    )
                )
            return retrieved
