# Healthcare Contract Auditor

An AI-powered REST API that audits healthcare **provider contract PDFs** against CMS
Medicare Physician Fee Schedule data, producing a PASS/FAIL JSON report with structured
error codes (`TF001` timely filing, `FS002` fee-schedule deviation, `LL003` lesser-of, …).

**The AI proposes, the SQL disposes.** An LLM only *extracts* contract values into
validated Pydantic JSON; a deterministic SQL rules engine does the financial comparison —
so there is no hallucination risk on regulated dollar figures.

> Portfolio project. Built from public CMS data and a generic architectural pattern.
> Sample contracts under `data/contracts/` are **synthetic** and clearly labelled.

## Architecture — a 5-stage pipeline behind `POST /audit_contract`

```
            ┌─────────── agents/llm_client.py (provider abstraction) ───────────┐
            │     github · azure · groq   —   one OpenAI-compatible interface    │
            └───────────────────────────────────────────────────────────────────┘
                              ▲                         ▲
  Stage 1            Stage 2  │            Stage 3      │        Stage 4         Stage 5
 ┌────────┐        ┌────────┐ │ chat+embed ┌─────────┐  │ embed ┌──────────┐   ┌──────────┐
 │ agree- │  →     │ docs + │─┴───────────▶│  RAG    │──┴──────▶│ timeline │ → │  strict  │→ report
 │ ment   │        │ cache  │              │ extract │         │ reconcile│   │  grader  │  (PASS/FAIL
 │ check  │        │(Blob + │              │(Pydantic│         │(amend-   │   │ (6 case  │   + codes)
 │(SQL)   │        │ Search)│              │ outputs)│         │ ments)   │   │  types,  │
 └────────┘        └────────┘              └─────────┘         └──────────┘   │  SQL)    │
                                                                              └──────────┘
```

1. **Pre-check** — verify the provider agreement is active (`facets_sim.provider_agreement`).
2. **Retrieval & cache** — find contract PDFs (`app_config.meta_index`), pull from Blob,
   check the response cache keyed on `(doc_hash, prompt_hash, provider)`.
3. **AI extraction** — RAG over Azure AI Search; extract Timely Filing, Lesser-of, and
   reimbursement rates into Pydantic models via forced tool-calling.
4. **Timeline** — reconcile effective/terminate dates across amendments.
5. **Strict grader** — map to one of 6 case types; parameterized SQL audit against
   `facets_sim`; emit coded findings and persist to `app_config.audit_runs`.

## LLM provider matrix

All LLM/embedding calls go through `agents/llm_client.py`. Switch backends with one env
var — no code changes:

| `LLM_PROVIDER`  | Role               | base_url                                | Key env            | Default model              |
| --------------- | ------------------ | --------------------------------------- | ------------------ | -------------------------- |
| `github` (def.) | Primary (dev/demo) | `https://models.inference.ai.azure.com` | `GITHUB_TOKEN`     | `gpt-4o-mini`              |
| `azure`         | Production target  | `AZURE_OPENAI_ENDPOINT` (+ deployment)  | `AZURE_OPENAI_KEY` | `AZURE_OPENAI_DEPLOYMENT`  |
| `groq`          | High-throughput    | `https://api.groq.com/openai/v1`        | `GROQ_API_KEY`     | `llama-3.3-70b-versatile`  |

## Tech stack

Python 3.12 target, FastAPI, Uvicorn · LangChain-style RAG · Azure AI Search (vectors) ·
Azure SQL (`facets_sim` + `app_config` schemas, async via `aioodbc`) · Azure Blob ·
Azure Key Vault · Bicep IaC · `uv` · `ruff` · `pyright` · `pytest`.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env           # then add your GITHUB_TOKEN
uvicorn app:app --reload
curl http://127.0.0.1:8000/health     # {"status":"ok","provider":"github","version":"0.1.0"}
```

See **[SETUP.md](SETUP.md)** for the full credentials + Azure provisioning walkthrough.

## Development

```powershell
pip install -r requirements-dev.txt   # ruff, pyright, pytest (one-time)
ruff check .                          # lint
ruff format --check .                 # formatting
pyright                               # type-check
pytest                                # 43 unit tests (live tests skipped)
pytest -m live                        # opt-in live LLM smoke test (needs GITHUB_TOKEN)
```

## Project layout

```
app.py                     FastAPI routes + lifespan (builds the pipeline)
pipeline.py                5-stage orchestration (AuditPipeline)
models.py                  Pydantic v2 schemas (extraction, timeline, report, error codes)
config.py                  Settings (pydantic-settings), version, secret resolution
agents/
  llm_client.py            Provider abstraction: chat_structured() + embed()  ← only LLM entry point
  agent_rag.py             RAG retrieval, DB prompt registry, response cache, extraction
document_extraction/
  pdf_ingest.py            PDF → Blob → chunk → embed → AI Search
  blob_store.py            Azure Blob wrapper
  search_index.py          Azure AI Search vector index (write + read)
  timeline_builder.py      Amendment reconciliation
facets/
  fee_extraction.py        Normalize/dedupe AI output, map terminology to codes
  multi_records.py         Regex provider-type standardization, facility inference
  fee_validation.py        Strict grader: 6 case types, parameterized SQL, error codes
db/
  database.py              Async aioodbc connection pool
  repository.py            Typed repositories (parameterized SQL only)
  schema_facets_sim.sql    CMS/Facets ground-truth DDL
  schema_app_config.sql    App-state DDL (cache, prompts, audit runs)
  seed_mpfs.py             Load data/mpfs_2025.csv into facets_sim.mpfs_fee
  seed_reference.py        Seed agreements, benchmarks, prompt registry
infra/bicep/               Azure IaC (SQL, AI Search, Blob, Key Vault, App Service F1)
data/                      Synthetic contracts (PDF) + sample MPFS CSV
tests/                     pytest mirrors the source tree
```

## Verification status

| Check                                              | Status |
| -------------------------------------------------- | ------ |
| `ruff check` / `ruff format --check`               | ✅ pass |
| `pyright` (standard mode, full project)            | ✅ pass |
| `pytest` (43 unit tests, mocked Azure/LLM)         | ✅ pass |
| App boots, `/health` returns the right shape       | ✅ pass |
| Synthetic PDFs parse (pypdf)                        | ✅ pass |
| Live LLM call, AI Search, Blob, Azure SQL, deploy  | ⏳ needs your token + Azure subscription (see SETUP.md) |

## Environment notes

- **Python**: targets **3.12** (ruff + pyright pinned to `py312`); runs fine on 3.12 or 3.13.
- **Behind a corporate proxy?** `pip` works as-is. The LLM HTTP client verifies against the
  OS trust store, and `pyright[nodejs]` ships Node as a PyPI wheel (so pyright never needs to
  download Node from nodejs.org).
