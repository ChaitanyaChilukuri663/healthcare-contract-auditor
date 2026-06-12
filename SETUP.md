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

## 5. Deploy to Azure (student subscription)

The full `POST /audit_contract` flow needs Azure SQL, AI Search, Blob, and (optionally)
Key Vault + App Service. Everything is scripted under `infra/`.

> **Use Azure Cloud Shell** (the `>_` icon at https://portal.azure.com). It runs in the
> browser with `az`, `bicep`, `sqlcmd`, `git`, and `python` preinstalled — so you avoid
> installing anything locally (handy here, where downloads are restricted). You're already
> logged in inside Cloud Shell.
>
> **Heads-up — ODBC driver:** `pyodbc` needs *ODBC Driver 18 for SQL Server*. It's present
> on the App Service Linux image, so the recommended target is **deploying the app to App
> Service** rather than running it on a machine that lacks the driver.

### 5a. Before you start
- Set a **$20 budget alert** in Azure Cost Management.
- In Cloud Shell, get the code: `git clone https://github.com/ChaitanyaChilukuri663/healthcare-contract-auditor && cd healthcare-contract-auditor`

### 5b. Validate + deploy the infrastructure
```bash
# Validate the Bicep first (catches template errors before anything is created):
az bicep build --file infra/bicep/main.bicep

# Deploy (free/cheapest tiers). See infra/bicep/README.md for what's created.
export SQL_ADMIN_PASSWORD='<a-strong-password>'
cd infra && bash deploy.sh && cd ..
```
Note the printed outputs: SQL server FQDN, search endpoint, storage account, web app name,
Key Vault URI.

### 5c. Create schemas + seed (driver-free, via sqlcmd)
```bash
S=<sqlServerFqdn>; U=<sqlAdmin>; P="$SQL_ADMIN_PASSWORD"
sqlcmd -S $S -d hca -U $U -P "$P" -i db/schema_facets_sim.sql
sqlcmd -S $S -d hca -U $U -P "$P" -i db/schema_app_config.sql
sqlcmd -S $S -d hca -U $U -P "$P" -i db/seed_data.sql      # reference data + sample MPFS
```
`db/seed_data.sql` needs no Python/pyodbc. (`db/seed_mpfs.py` / `db/seed_reference.py` do the
same via Python if you prefer.)

### 5d. Store secrets in Key Vault
The Bicep wires App Service settings to Key Vault references, so populate the vault:
```bash
V=<keyVaultName>
az keyvault secret set --vault-name $V --name GITHUB-TOKEN --value '<your_github_token>'
az keyvault secret set --vault-name $V --name AZURE-SEARCH-KEY --value '<search_admin_key>'
az keyvault secret set --vault-name $V --name AZURE-SQL-CONNECTION-STRING --value '<odbc_conn_str>'
az keyvault secret set --vault-name $V --name AZURE-BLOB-CONNECTION-STRING --value '<blob_conn_str>'
```
(Key Vault names use dashes; app settings use underscores — see `infra/bicep/README.md`.)

### 5e. Deploy the app code to App Service
```bash
az webapp up --name <webAppName> --runtime "PYTHON:3.12" --sku F1
# or configure GitHub deployment from the repo in the Portal (Deployment Center).
```
Then open `https://<webAppName>.azurewebsites.net/health`.

### 5f. Ingest the sample contracts
Run from a place that has the app deps + ODBC Driver 18 (App Service SSH console, or your
laptop once Driver 18 is installed), with the `AZURE_*` env vars set:
```bash
python -m document_extraction.ingest_cli --demo
```
This uploads the 3 synthetic PDFs to Blob, embeds + indexes them in AI Search, and records
them in `meta_index`. After that, `POST /audit_contract` returns a full report:
```bash
curl -X POST https://<webAppName>.azurewebsites.net/audit_contract \
  -H "Content-Type: application/json" \
  -d '{"provider_npi":"1234567890","state":"TX","lob":"Medicare","contract_id":"C-TX-001"}'
# Provider A -> PASS ; Provider B (1987654321 / NY / Medicaid / C-NY-001) -> FAIL with codes
```

---

## What's verified vs. needs your live Azure run

- ✅ Verified locally: lint (ruff), format, types (pyright), 43 unit tests, app boots +
  `/health`, synthetic PDFs parse.
- ⏳ You verify on Azure: `az bicep build` + deploy, the live LLM call, AI Search/Blob/SQL,
  ingestion, and an end-to-end `POST /audit_contract`. The Bicep hasn't been compiled yet —
  run `az bicep build` first (5b) and share any error; it's a quick fix.
