"""Application configuration: env loading, typed settings, and version lookup.

Secrets come from the environment (a local ``.env`` in dev; App Service application
settings in prod).
"""

import functools
import logging
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
_ENV_FILE = PROJECT_ROOT / ".env"


class ConfigurationError(RuntimeError):
    """Raised when a required piece of configuration is missing."""


@functools.cache
def load_env() -> None:
    """Load the project ``.env`` into ``os.environ`` once (dev convenience)."""
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE)
        logger.debug("Loaded environment from %s", _ENV_FILE)


@functools.cache
def get_version() -> str:
    """Return the project version declared in ``pyproject.toml``."""
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


class Settings(BaseSettings):
    """App-level settings. LLM-provider config lives in ``agents.llm_client``."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = Field(default="healthcare-contract-auditor", description="Service name.")
    audit_concurrency: int = Field(
        default=1, ge=1, description="Max concurrent /audit_contract requests (semaphore bound)."
    )
    request_timeout_seconds: float = Field(
        default=60.0, gt=0, description="Default timeout (seconds) for outbound LLM/HTTP calls."
    )

    # --- Embeddings & chunking ---
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding model (provider-hosted)."
    )
    embedding_dimensions: int = Field(
        default=1536, gt=0, description="Embedding vector dimensions (AI Search vector field)."
    )
    chunk_max_tokens: int = Field(default=500, gt=0, description="Max tokens per document chunk.")
    chunk_overlap_tokens: int = Field(
        default=80, ge=0, description="Token overlap between adjacent chunks."
    )

    # --- Validation tolerances (Stage 5) ---
    percent_tolerance: float = Field(
        default=0.5, ge=0, description="Allowed deviation (percentage points) for rate matches."
    )
    amount_tolerance: float = Field(
        default=0.01, ge=0, description="Allowed deviation (dollars) for dollar-amount matches."
    )
    default_locality: str = Field(
        default="0000000", description="CMS locality code used for fee-schedule lookups."
    )

    # --- Azure AI Search ---
    azure_search_endpoint: str | None = Field(default=None, description="AI Search endpoint URL.")
    azure_search_key: str | None = Field(default=None, description="AI Search admin/query key.")
    azure_search_index: str = Field(
        default="contract-chunks", description="AI Search index name for contract chunks."
    )

    # --- Azure Blob Storage ---
    azure_blob_connection_string: str | None = Field(
        default=None, description="Blob connection string (dev). Prefer identity in prod."
    )
    azure_blob_account_url: str | None = Field(
        default=None, description="Blob account URL (used with managed identity)."
    )
    blob_container: str = Field(default="contracts", description="Blob container for raw PDFs.")

    # --- Azure SQL ---
    azure_sql_connection_string: str | None = Field(
        default=None, description="Full ODBC connection string (overrides components below)."
    )
    azure_sql_server: str | None = Field(default=None, description="SQL server FQDN.")
    azure_sql_database: str | None = Field(default=None, description="SQL database name.")
    azure_sql_username: str | None = Field(default=None, description="SQL username.")
    azure_sql_password: str | None = Field(default=None, description="SQL password.")
    azure_sql_driver: str = Field(
        default="{ODBC Driver 18 for SQL Server}", description="ODBC driver name."
    )

    def sql_connection_string(self) -> str:
        """Return the ODBC connection string, building it from components if needed."""
        if self.azure_sql_connection_string:
            return self.azure_sql_connection_string
        if self.azure_sql_server and self.azure_sql_database:
            return (
                f"DRIVER={self.azure_sql_driver};"
                f"SERVER={self.azure_sql_server};"
                f"DATABASE={self.azure_sql_database};"
                f"UID={self.azure_sql_username};PWD={self.azure_sql_password};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
            )
        raise ConfigurationError(
            "Azure SQL is not configured: set AZURE_SQL_CONNECTION_STRING or "
            "AZURE_SQL_SERVER/AZURE_SQL_DATABASE (+ credentials)."
        )


@functools.cache
def get_settings() -> Settings:
    """Return cached application settings, loading ``.env`` first."""
    load_env()
    return Settings()
