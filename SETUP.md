# Setup & Credentials Guide

From a fresh clone to a running service, then (optionally) a full Azure deploy.
Commands assume Windows PowerShell; macOS/Linux equivalents are noted.

---

## 1. Create a virtual environment and install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # + test/lint tools (optional)
```

A *virtual environment* (`.venv`) is just a private folder of libraries for this project,
so it doesn't clash with other Python projects. Activate it in each new terminal.

## 2. Create your `.env`

```powershell
Copy-Item .env.example .env
```

Then edit `.env`. **Minimum to start the service + LLM paths:**

| Variable        | Value                        |
| --------------- | ---------------------------- |
| `LLM_PROVIDER`  | `github`                     |
| `GITHUB_TOKEN`  | a GitHub token (see step 3)  |

The `AZURE_*` values are only needed for the full `POST /audit_contract` pipeline (step 5).
Without them the service still runs and serves `/health`.

## 3. Get a GitHub Models token (free, no credit card)

1. Go to **https://github.com/settings/tokens**.
2. *Fine-grained tokens* → **Generate new token** (no special permissions needed for
   GitHub Models). A classic token with no scopes also works.
3. Copy the token into `.env` as `GITHUB_TOKEN`.
4. Free tier: **150 requests/day** on `gpt-4o-mini`. Endpoint
   `https://models.inference.ai.azure.com` is set in code.

> ⚠️ If your token only works with the newer host `https://models.github.ai/inference`,
> update `GITHUB_BASE_URL` in `agents/llm_client.py`.

## 4. Run locally

```powershell
uvicorn app:app --reload                 # http://127.0.0.1:8000
# in another shell (venv activated):
curl http://127.0.0.1:8000/health
pytest -m live                           # live LLM smoke test (uses your GITHUB_TOKEN)
```

---

## 5. Provision Azure (for the full pipeline) — optional

The full `POST /audit_contract` flow needs Azure SQL, AI Search, Blob, and (optionally)
Key Vault. Everything is scripted under `infra/`.

### 5a. Prerequisites
- Azure CLI (`az login`, `az account set --subscription <id>`) and `az bicep install`.
- **Set a $20 budget alert** in Azure Cost Management before deploying.

### 5b. Deploy infrastructure
```bash
export SQL_ADMIN_PASSWORD='<a-strong-password>'
cd infra && bash deploy.sh
```
Creates the resource group and all resources (free/cheapest tiers) and prints endpoints.
See `infra/bicep/README.md` for what's deployed and the free-tier caps.

### 5c. Create the database schemas
```bash
sqlcmd -S <server>.database.windows.net -d hca -U <admin> -P "$SQL_ADMIN_PASSWORD" -i db/schema_facets_sim.sql
sqlcmd -S <server>.database.windows.net -d hca -U <admin> -P "$SQL_ADMIN_PASSWORD" -i db/schema_app_config.sql
```

### 5d. Seed data
Fill the `AZURE_SQL_*` values in `.env`, then (venv activated):
```powershell
python -m db.seed_mpfs        # CMS MPFS rows from data/mpfs_2025.csv
python -m db.seed_reference   # provider agreements, benchmarks, prompt registry
```

### 5e. Ingest the sample contracts
Fill `AZURE_SEARCH_*` and `AZURE_BLOB_*` in `.env`. The synthetic PDFs are in
`data/contracts/`. `document_extraction.pdf_ingest.PdfIngestor.ingest(...)` uploads to Blob,
embeds, and indexes in AI Search.

### 5f. Store secrets in Key Vault (prod)
App Service resolves Key Vault references into the environment (wired by the Bicep). E.g.:
```bash
az keyvault secret set --vault-name <vault> --name GITHUB-TOKEN --value '<token>'
```
(Key Vault secret names use dashes; app settings use underscores — see `infra/bicep/README.md`.)

---

## What's verified vs. needs a live Azure run

- ✅ Verified locally: lint (ruff), format, types (pyright), 43 unit tests, the app boots
  and serves `/health`, and the synthetic PDFs parse.
- ⏳ Needs your token + an Azure subscription: the live LLM smoke test, AI Search indexing,
  Blob upload, Azure SQL queries, and a full `POST /audit_contract` run.
