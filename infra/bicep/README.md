# Infrastructure (Azure Bicep)

Infrastructure-as-code for the **healthcare-contract-auditor** FastAPI app. All
resources are provisioned on **Free / cheapest tiers** with a steady-state spend
target of **under $5/month** (assuming you stay inside the free caps below).

## What gets deployed

`main.bicep` (resource-group scope) composes six modules under `modules/`:

| Module | Resource(s) | Tier / SKU |
| --- | --- | --- |
| `sql.bicep` | Azure SQL logical server + 1 database `hca` | GP Serverless **Free offer** (Basic DTU fallback) |
| `search.bicep` | Azure AI Search service | **free** |
| `storage.bicep` | Storage account + `contracts` blob container | Standard_LRS |
| `keyvault.bicep` | Key Vault (RBAC-authorized) | standard |
| `appservice.bicep` | Linux App Service Plan + Python Web App | **F1 (Free)**, runtime `PYTHON\|3.12` |
| `insights.bicep` | Log Analytics workspace + Application Insights | PerGB2018, 1 GB/day cap |

The two application schemas — `facets_sim` (CMS MPFS fee data) and `app_config`
(cache, prompts, audit runs) — live **inside the single `hca` database** and are
created by SQL DDL (`db/schema_*.sql`), **not** by Bicep.

### Identity & secrets wiring

- The Web App has a **system-assigned managed identity**, granted three
  least-privilege RBAC roles:
  - **Key Vault Secrets User** on the vault
  - **Storage Blob Data Contributor** on the storage account
  - **Search Index Data Contributor** on the search service
- App settings reference secrets via `@Microsoft.KeyVault(SecretUri=...)`, so
  no secret values appear in the template or deployment history:
  `GITHUB_TOKEN`, `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_KEY`,
  `AZURE_SQL_CONNECTION_STRING`, `AZURE_BLOB_CONNECTION_STRING`,
  `AZURE_KEYVAULT_URI` (plus non-secret `LLM_PROVIDER=github`).

> **Runtime note:** the Web App uses Azure's `PYTHON|3.12` image tag. The code
> is 3.13-compatible (`requires-python >=3.12`), but Azure App Service does not
> publish a `PYTHON|3.13` runtime image, so `3.12` is the correct value.

## Free-tier caveats (do not exceed these)

- **Azure AI Search (free):** 50 MB total storage, **3 indexes max**, 1
  replica / 1 partition, no SLA, shared infrastructure.
- **Azure SQL (GP Serverless free offer):** ~32 GB storage and a capped monthly
  vCore-seconds allowance; **one free database per subscription**. AutoPause
  after 60 min idle (first request after a pause incurs a cold-start delay).
  `freeLimitExhaustionBehavior` is set to **AutoPause** so you are not billed
  when the free allowance is spent — the DB pauses instead. If the free offer
  is unavailable in your subscription/region, redeploy with
  `useGPServerlessFreeOffer=false` to use the **Basic** DTU tier (~$5/mo, 2 GB).
- **App Service F1 (Free):** 60 CPU-minutes/day, 1 GB RAM, 1 GB storage,
  **no "Always On"** (cold starts expected), shared compute. Custom domains/SSL
  and scale-out are unavailable on F1.
- **Application Insights / Log Analytics:** 5 GB/month free ingestion grant;
  this template additionally caps Log Analytics at **1 GB/day**.
- **Storage (Standard_LRS):** pennies for POC volumes; the only meaningful cost
  driver if you store many large PDFs.

## How to run

```bash
# 1. Log in and pick the subscription
az login
az account set --subscription "<SUBSCRIPTION_NAME_OR_ID>"

# 2. (Recommended) create a $20 Cost Management budget alert first — see the
#    header comment in deploy.sh.

# 3. Provide the SQL admin password via env var (never commit it)
export SQL_ADMIN_PASSWORD='<a-strong-password>'

# 4. Deploy (optionally override RG_NAME / LOCATION / NAME_PREFIX / SQL_ADMIN_LOGIN)
./deploy.sh
```

`deploy.sh` creates the resource group, runs `az deployment group create`
non-interactively, and prints the outputs plus next steps.

To validate the template without deploying:

```bash
az bicep build --file bicep/main.bicep          # compile-only syntax check
az deployment group what-if \
  --resource-group rg-healthcare-contract-auditor \
  --template-file bicep/main.bicep \
  --parameters sqlAdminLogin=hcaadmin sqlAdminPassword="$SQL_ADMIN_PASSWORD"
```

## Setting the Key Vault secrets after deploy

The template creates the secret **references** but not their **values**. After
deploying, set the actual secrets (note the **dash-separated** secret names —
Key Vault secret names cannot contain underscores, while the corresponding app
settings use underscores):

```bash
VAULT=<vault-name>   # the segment between https:// and .vault.azure.net in keyVaultUri

# LLM provider token (GitHub Models)
az keyvault secret set --vault-name "$VAULT" --name GITHUB-TOKEN \
  --value "ghp_xxxxxxxxxxxxxxxxxxxx"

# Azure AI Search (endpoint from the deploy output; key from the service)
az keyvault secret set --vault-name "$VAULT" --name AZURE-SEARCH-ENDPOINT \
  --value "https://<search-name>.search.windows.net"
az keyvault secret set --vault-name "$VAULT" --name AZURE-SEARCH-KEY \
  --value "$(az search admin-key show --service-name <search-name> \
              --resource-group <rg> --query primaryKey -o tsv)"

# Azure SQL connection string (ODBC / pyodbc form)
az keyvault secret set --vault-name "$VAULT" --name AZURE-SQL-CONNECTION-STRING \
  --value "Driver={ODBC Driver 18 for SQL Server};Server=tcp:<sql-fqdn>,1433;Database=hca;Uid=hcaadmin;Pwd=<password>;Encrypt=yes;TrustServerCertificate=no;"

# Azure Blob connection string
az keyvault secret set --vault-name "$VAULT" --name AZURE-BLOB-CONNECTION-STRING \
  --value "$(az storage account show-connection-string \
              --name <storage-account> --resource-group <rg> -o tsv)"

# Key Vault URI (self-reference, used by app code for runtime secret reads)
az keyvault secret set --vault-name "$VAULT" --name AZURE-KEYVAULT-URI \
  --value "https://$VAULT.vault.azure.net/"
```

| App setting (env var) | Key Vault secret name |
| --- | --- |
| `GITHUB_TOKEN` | `GITHUB-TOKEN` |
| `AZURE_SEARCH_ENDPOINT` | `AZURE-SEARCH-ENDPOINT` |
| `AZURE_SEARCH_KEY` | `AZURE-SEARCH-KEY` |
| `AZURE_SQL_CONNECTION_STRING` | `AZURE-SQL-CONNECTION-STRING` |
| `AZURE_BLOB_CONNECTION_STRING` | `AZURE-BLOB-CONNECTION-STRING` |
| `AZURE_KEYVAULT_URI` | `AZURE-KEYVAULT-URI` |

After setting secrets, restart the Web App so it re-resolves the references:

```bash
az webapp restart --name <web-app-name> --resource-group <rg>
```

## Database schema (manual, post-deploy)

Bicep provisions only server + database. Create the schemas and seed data:

```bash
sqlcmd -S <sql-fqdn> -d hca -U hcaadmin -P "$SQL_ADMIN_PASSWORD" \
  -i ../../db/schema_facets_sim.sql
sqlcmd -S <sql-fqdn> -d hca -U hcaadmin -P "$SQL_ADMIN_PASSWORD" \
  -i ../../db/schema_app_config.sql
python ../../db/seed_mpfs.py
```
