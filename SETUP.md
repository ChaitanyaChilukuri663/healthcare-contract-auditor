# Setup & Credentials Guide

This walks you from a fresh clone to a running service, then to a full Azure deploy.
On this machine `uv` is not on PATH — use the full path shown below (or add
`%LOCALAPPDATA%\Programs\Python\Python313\Scripts` to PATH once).

```powershell
$uv = "$env:LOCALAPPDATA\Programs\Python\Python313\Scripts\uv.exe"
```

---

## 1. Install dependencies

```powershell
& $uv sync --directory "C:\RAG"
```

This creates `.venv` and installs everything. `pyproject.toml` already sets
`system-certs = true` (to trust the corporate proxy CA) and `python-preference = "only-system"`.

## 2. Create your `.env`

```powershell
Copy-Item "C:\RAG\.env.example" "C:\RAG\.env"
```

Then edit `C:\RAG\.env`. **Minimum to start the service + LLM paths:**

| Variable        | Value                                                        |
| --------------- | ------------------------------------------------------------ |
| `LLM_PROVIDER`  | `github`                                                     |
| `GITHUB_TOKEN`  | a GitHub token (see step 3)                                  |

The `AZURE_*` values are only needed for the full `POST /audit_contract` pipeline
(step 5). Without them the service still runs and serves `/health`.

## 3. Get a GitHub Models token (free, no credit card)

1. Go to **https://github.com/settings/tokens**.
2. *Fine-grained tokens* → **Generate new token** (no repo/account permissions are
   needed for GitHub Models — a token with default read access is enough). A classic
   token with no scopes also works.
3. Copy the token (starts with `github_pat_` or `ghp_`) into `.env` as `GITHUB_TOKEN`.
4. Free tier: **150 requests/day** on `gpt-4o-mini`. Endpoint is
   `https://models.inference.ai.azure.com` (set in code).

> ⚠️ Endpoint note: GitHub later introduced `https://models.github.ai/inference`. The
> code uses the value from CLAUDE.md (`models.inference.ai.azure.com`). If your token
> only works with the newer host, update `GITHUB_BASE_URL` in `agents/llm_client.py`.

## 4. Run locally (health + LLM smoke test)

```powershell
& $uv run --directory "C:\RAG" uvicorn app:app --reload     # http://127.0.0.1:8000
# in another shell:
curl http://127.0.0.1:8000/health
# Live LLM smoke test (uses your GITHUB_TOKEN):
& $uv run --directory "C:\RAG" pytest -m live
```

---

## 5. Provision Azure (for the full pipeline) — optional

The full `POST /audit_contract` flow needs Azure SQL, AI Search, Blob, and (optionally)
Key Vault. Everything is scripted under `infra/`.

### 5a. Prerequisites
- Azure CLI (`az login`, `az account set --subscription <id>`).
- The Bicep CLI (`az bicep install`).
- **Set a $20 budget alert** in Azure Cost Management before deploying.

### 5b. Deploy infrastructure
```bash
export SQL_ADMIN_PASSWORD='<a-strong-password>'
cd infra
bash deploy.sh
```
This creates the resource group and all resources (free/cheapest tiers) and prints the
endpoints. See `infra/bicep/README.md` for what's deployed and the free-tier caps.

### 5c. Create the database schemas
Run the DDL against the new Azure SQL DB (sqlcmd or Azure Data Studio):
```bash
sqlcmd -S <server>.database.windows.net -d hca -U <admin> -P "$SQL_ADMIN_PASSWORD" -i db/schema_facets_sim.sql
sqlcmd -S <server>.database.windows.net -d hca -U <admin> -P "$SQL_ADMIN_PASSWORD" -i db/schema_app_config.sql
```

### 5d. Seed data
Fill the `AZURE_SQL_*` values in `.env`, then:
```powershell
& $uv run --directory "C:\RAG" python -m db.seed_mpfs        # CMS MPFS rows
& $uv run --directory "C:\RAG" python -m db.seed_reference   # agreements, benchmarks, prompts
```

### 5e. Ingest the sample contracts
Fill `AZURE_SEARCH_*` and `AZURE_BLOB_*` in `.env`. The synthetic PDFs are in
`data/contracts/`. (An ingestion CLI lands as a follow-up; `document_extraction.pdf_ingest.PdfIngestor`
is the entry point — `ingest(...)` uploads to Blob, embeds, and indexes in AI Search.)

### 5f. Store secrets in Key Vault (prod)
App Service resolves Key Vault references into the environment (wired by the Bicep).
Example:
```bash
az keyvault secret set --vault-name <vault> --name GITHUB-TOKEN --value '<token>'
az keyvault secret set --vault-name <vault> --name AZURE-SQL-CONNECTION-STRING --value '<conn>'
```
(Key Vault secret names use dashes; app settings use underscores — see `infra/bicep/README.md`.)

---

## What's verified vs. needs a live Azure run

- ✅ Verified here: lint (ruff), format, types (pyright), 43 unit tests, the app boots
  and serves `/health`, and the synthetic PDFs parse.
- ⏳ Needs your Azure + token to verify end-to-end: the live LLM smoke test, AI Search
  indexing, Blob upload, Azure SQL queries, and a full `POST /audit_contract` run.
