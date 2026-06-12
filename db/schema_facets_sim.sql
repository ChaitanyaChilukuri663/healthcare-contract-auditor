-- schema_facets_sim.sql
-- Facets stand-in: CMS MPFS ground truth + provider agreements + benchmark policy.
-- Idempotent; run with sqlcmd (GO batch separators) against the target Azure SQL DB.

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'facets_sim')
    EXEC('CREATE SCHEMA facets_sim');
GO

-- Provider agreements (Stage 1 pre-check).
IF OBJECT_ID('facets_sim.provider_agreement', 'U') IS NULL
CREATE TABLE facets_sim.provider_agreement (
    provider_npi    VARCHAR(10)  NOT NULL,
    contract_id     VARCHAR(50)  NOT NULL,
    state           CHAR(2)      NOT NULL,
    lob             VARCHAR(50)  NOT NULL,
    effective_date  DATE         NOT NULL,
    terminate_date  DATE         NULL,
    CONSTRAINT pk_provider_agreement PRIMARY KEY (provider_npi, contract_id, state)
);
GO

-- CMS Medicare Physician Fee Schedule (seeded from data/mpfs_2025.csv).
IF OBJECT_ID('facets_sim.mpfs_fee', 'U') IS NULL
CREATE TABLE facets_sim.mpfs_fee (
    cpt_code           VARCHAR(10)    NOT NULL,
    locality           VARCHAR(10)    NOT NULL,
    description        NVARCHAR(256)  NULL,
    conversion_factor  DECIMAL(10, 4) NULL,
    rvu                DECIMAL(10, 4) NULL,
    amount             DECIMAL(12, 2) NOT NULL,
    CONSTRAINT pk_mpfs_fee PRIMARY KEY (cpt_code, locality)
);
GO

-- Timely-filing benchmark by (state, lob).
IF OBJECT_ID('facets_sim.filing_rule', 'U') IS NULL
CREATE TABLE facets_sim.filing_rule (
    state         CHAR(2)     NOT NULL,
    lob           VARCHAR(50) NOT NULL,
    days_to_file  INT         NOT NULL,
    CONSTRAINT pk_filing_rule PRIMARY KEY (state, lob)
);
GO

-- Reimbursement policy benchmark by (state, lob).
IF OBJECT_ID('facets_sim.reimbursement_policy', 'U') IS NULL
CREATE TABLE facets_sim.reimbursement_policy (
    state                     CHAR(2)        NOT NULL,
    lob                       VARCHAR(50)    NOT NULL,
    lesser_of_required        BIT            NOT NULL,
    expected_pct_of_medicare  DECIMAL(6, 2)  NULL,
    CONSTRAINT pk_reimbursement_policy PRIMARY KEY (state, lob)
);
GO
