-- schema_app_config.sql
-- Application state: document index, response cache, prompt registry, audit history.
-- Idempotent; run with sqlcmd (GO batch separators) against the target Azure SQL DB.

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'app_config')
    EXEC('CREATE SCHEMA app_config');
GO

-- Tracks every ingested contract PDF (Stage 2).
IF OBJECT_ID('app_config.meta_index', 'U') IS NULL
CREATE TABLE app_config.meta_index (
    doc_id          VARCHAR(64)    NOT NULL,
    provider_npi    VARCHAR(10)    NOT NULL,
    state           CHAR(2)        NOT NULL,
    doc_type        VARCHAR(20)    NOT NULL,
    blob_path       NVARCHAR(512)  NOT NULL,
    doc_hash        CHAR(64)       NOT NULL,
    effective_date  DATE           NULL,
    uploaded_at     DATETIME2      NOT NULL CONSTRAINT df_meta_uploaded DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_meta_index PRIMARY KEY (doc_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_meta_provider_state')
    CREATE INDEX ix_meta_provider_state
        ON app_config.meta_index (provider_npi, state);
GO

-- LLM response cache keyed on (doc_hash, prompt_hash, provider).
IF OBJECT_ID('app_config.doc_cache', 'U') IS NULL
CREATE TABLE app_config.doc_cache (
    doc_hash       CHAR(64)        NOT NULL,
    prompt_hash    CHAR(64)        NOT NULL,
    provider       VARCHAR(20)     NOT NULL,
    response_json  NVARCHAR(MAX)   NOT NULL,
    created_at     DATETIME2       NOT NULL CONSTRAINT df_cache_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_doc_cache PRIMARY KEY (doc_hash, prompt_hash, provider)
);
GO

-- Hot-reloadable extraction prompts.
IF OBJECT_ID('app_config.prompt_registry', 'U') IS NULL
CREATE TABLE app_config.prompt_registry (
    name         VARCHAR(64)    NOT NULL,
    prompt_text  NVARCHAR(MAX)  NOT NULL,
    updated_at   DATETIME2      NOT NULL CONSTRAINT df_prompt_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_prompt_registry PRIMARY KEY (name)
);
GO

-- Audit run history.
IF OBJECT_ID('app_config.audit_runs', 'U') IS NULL
CREATE TABLE app_config.audit_runs (
    run_id         INT IDENTITY(1, 1) NOT NULL,
    contract_id    VARCHAR(50)    NOT NULL,
    provider_npi   VARCHAR(10)    NOT NULL,
    state          CHAR(2)        NOT NULL,
    lob            VARCHAR(50)    NOT NULL,
    case_type      VARCHAR(64)    NULL,
    outcome        VARCHAR(10)    NOT NULL,
    checks_total   INT            NOT NULL,
    checks_failed  INT            NOT NULL,
    report_json    NVARCHAR(MAX)  NOT NULL,
    generated_at   DATETIME2      NOT NULL CONSTRAINT df_audit_generated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_audit_runs PRIMARY KEY (run_id)
);
GO
