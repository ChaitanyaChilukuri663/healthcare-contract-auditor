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
uvicorn app:app --reload                 # REST API: http://127.0.0.1:8000 (/health, /docs)
streamlit run streamlit_app.py           # visual UI: http://localhost:8501
# in another shell (venv activated):
curl http://127.0.0.1:8000/health
pytest -m live                           # live LLM smoke test (uses your GITHUB_TOKEN)
```

> The full audit (and the Streamlit "Run audit" button) needs the `AZURE_*` values + the
> ODBC driver locally. To just see the UI and `/health` without Azure, that's enough as-is.

---

## 5. Deploy to Azure (student subscription)

Use **Azure Cloud Shell** (the `>_` icon in the portal) for the `az`/`sqlcmd` steps — it has
everything preinstalled and you're already logged in. First set a **$20 budget alert**, then
`git clone https://github.com/ChaitanyaChilukuri663/healthcare-contract-auditor && cd healthcare-contract-auditor`.

> **Why a Docker container?** `pyodbc` needs *ODBC Driver 18*, which isn't in App Service's
> default Python image. The included **Dockerfile** installs it, so we deploy a container —
> this is the reliable path and gets Docker + App Service onto your resume.

### 5a. Create the resources (free where possible)
```bash
RG=hca-rg; LOC=eastus; PFX=hca$RANDOM; PW='<StrongPassw0rd!>'
az group create -n $RG -l $LOC

# Azure SQL — free offer (one free DB per subscription) + allow Azure services
az sql server create -g $RG -n $PFX-sql -l $LOC -u hcaadmin -p "$PW"
az sql db create -g $RG -s $PFX-sql -n hca \
  --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 2 \
  --use-free-limit --free-limit-exhaustion-behavior AutoPause
az sql server firewall-rule create -g $RG -s $PFX-sql -n azure \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0

az search service create -g $RG -n $PFX-search -l $LOC --sku free        # AI Search, free
az storage account create -g $RG -n ${PFX}stg -l $LOC --sku Standard_LRS
az storage container create --account-name ${PFX}stg -n contracts
```

### 5b. Schemas + seed (driver-free, via sqlcmd)
```bash
S=$PFX-sql.database.windows.net
sqlcmd -S $S -d hca -U hcaadmin -P "$PW" -i db/schema_facets_sim.sql
sqlcmd -S $S -d hca -U hcaadmin -P "$PW" -i db/schema_app_config.sql
sqlcmd -S $S -d hca -U hcaadmin -P "$PW" -i db/seed_data.sql          # reference + sample MPFS
```

### 5c. Build the image + deploy to App Service (Containers)
```bash
# Build the image in the cloud (no local Docker needed) and push to a registry
az acr create -g $RG -n ${PFX}acr --sku Basic --admin-enabled true
az acr build -r ${PFX}acr -t auditor:latest .

# App Service plan + web app (custom containers need Linux B1; Free/F1 can't run containers)
az appservice plan create -g $RG -n $PFX-plan --is-linux --sku B1
az webapp create -g $RG -p $PFX-plan -n $PFX-web \
  --deployment-container-image-name ${PFX}acr.azurecr.io/auditor:latest
az webapp config appsettings set -g $RG -n $PFX-web --settings WEBSITES_PORT=8000
```
> 💲 B1 + ACR Basic are ~**$13–18/mo** — well inside your $96, and you can stop all charges
> with `az group delete -n $RG` when you're done demoing. (A strictly-$0 route — F1 Python +
> a startup script that installs the driver — exists but is fiddly; the container is reliable.)

### 5d. App settings (secrets go straight into config — no Key Vault)
```bash
az webapp config appsettings set -g $RG -n $PFX-web --settings \
  LLM_PROVIDER=github GITHUB_TOKEN='<token>' \
  AZURE_SEARCH_ENDPOINT="https://$PFX-search.search.windows.net" \
  AZURE_SEARCH_KEY="$(az search admin-key show -g $RG --service-name $PFX-search --query primaryKey -o tsv)" \
  AZURE_SQL_SERVER="$S" AZURE_SQL_DATABASE=hca AZURE_SQL_USERNAME=hcaadmin AZURE_SQL_PASSWORD="$PW" \
  AZURE_BLOB_CONNECTION_STRING="$(az storage account show-connection-string -g $RG -n ${PFX}stg -o tsv)"
```
Open `https://$PFX-web.azurewebsites.net` — the Streamlit UI. (`/health` + `/docs` are served
by FastAPI if you run the API instead.)

### 5e. Ingest the sample contracts, then audit
The container already has the ODBC driver + the env vars, so ingest from inside it:
```bash
az webapp ssh -g $RG -n $PFX-web          # opens a shell in the running container
python -m document_extraction.ingest_cli --demo
```
Then in the Streamlit UI pick **Provider A → PASS** or **Provider B → FAIL with codes**.

---

## What's verified vs. needs your live Azure run

- ✅ Verified locally: `ruff` lint/format, **52 unit tests**, the app boots + `/health`, the
  Streamlit UI imports, and the synthetic PDFs parse.
- ⏳ You verify on Azure: resource creation, the live LLM call, AI Search/Blob/SQL, the Docker
  build + App Service deploy, ingestion, and an end-to-end audit. Paste any error and I'll fix it.
