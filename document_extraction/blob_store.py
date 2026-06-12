"""Azure Blob Storage wrapper for raw contract PDFs."""

import logging

from azure.storage.blob.aio import BlobServiceClient

from config import ConfigurationError

logger = logging.getLogger(__name__)


class BlobStore:
    """Uploads/downloads contract PDFs to/from a Blob container."""

    def __init__(
        self,
        container: str,
        connection_string: str | None = None,
        account_url: str | None = None,
    ) -> None:
        self._container = container
        self._connection_string = connection_string
        self._account_url = account_url

    def _service(self) -> BlobServiceClient:
        if self._connection_string:
            return BlobServiceClient.from_connection_string(self._connection_string)
        if self._account_url:
            from azure.identity.aio import DefaultAzureCredential

            return BlobServiceClient(self._account_url, credential=DefaultAzureCredential())
        raise ConfigurationError(
            "Blob storage is not configured: set AZURE_BLOB_CONNECTION_STRING or "
            "AZURE_BLOB_ACCOUNT_URL."
        )

    async def upload_pdf(self, name: str, data: bytes) -> str:
        """Upload PDF bytes and return the blob URL."""
        async with self._service() as service:
            container = service.get_container_client(self._container)
            blob = container.get_blob_client(name)
            await blob.upload_blob(data, overwrite=True)
            logger.info("Uploaded blob %s (%d bytes)", name, len(data))
            return blob.url

    async def download_pdf(self, name: str) -> bytes:
        """Download PDF bytes by blob name."""
        async with self._service() as service:
            container = service.get_container_client(self._container)
            blob = container.get_blob_client(name)
            stream = await blob.download_blob()
            return await stream.readall()
