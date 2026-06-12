#!/usr/bin/env bash
# ===========================================================================
# deploy.sh — one-command deploy of the healthcare-contract-auditor infra
# ---------------------------------------------------------------------------
# PREREQUISITES
#   1. Azure CLI installed and logged in:
#          az login
#      and the correct subscription selected:
#          az account set --subscription "<SUBSCRIPTION_NAME_OR_ID>"
#   2. Bicep CLI available (bundled with recent az; `az bicep install` if not).
#   3. Export the SQL admin password (NOT committed anywhere) before running:
#          export SQL_ADMIN_PASSWORD='<a-strong-password>'
#
#   COST GUARD — BEFORE YOU DEPLOY:
#      Create a Cost Management budget with an alert (e.g. $20) so a misconfig
#      cannot run up charges. Portal: Cost Management + Billing → Budgets → Add;
#      or CLI:
#          az consumption budget create \
#            --budget-name hca-poc-budget --amount 20 --time-grain Monthly \
#            --category Cost --start-date "$(date -u +%Y-%m-01)" \
#            --end-date "$(date -u -d '+1 year' +%Y-%m-01)"
#      (CLI budget syntax varies by az version; the Portal route is simplest.)
#
#   The target steady-state spend for this stack is < $5/mo on free/cheapest
#   tiers, but ONLY if you stay within the free caps (see README.md).
# ===========================================================================

set -euo pipefail

# --------------------------- Configuration ---------------------------------
RG_NAME="${RG_NAME:-rg-healthcare-contract-auditor}"
LOCATION="${LOCATION:-eastus}"
NAME_PREFIX="${NAME_PREFIX:-hca}"
SQL_ADMIN_LOGIN="${SQL_ADMIN_LOGIN:-hcaadmin}"
DEPLOYMENT_NAME="hca-infra-$(date -u +%Y%m%d-%H%M%S)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/bicep/main.bicep"

# --------------------------- Pre-flight checks -----------------------------
if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: Azure CLI (az) not found on PATH. Install it and run 'az login'." >&2
  exit 1
fi

if [[ -z "${SQL_ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: SQL_ADMIN_PASSWORD env var is not set." >&2
  echo "       Run: export SQL_ADMIN_PASSWORD='<a-strong-password>'" >&2
  exit 1
fi

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
  echo "ERROR: Bicep template not found at ${TEMPLATE_FILE}" >&2
  exit 1
fi

# --------------------------- Deploy ----------------------------------------
echo ">> Creating resource group '${RG_NAME}' in '${LOCATION}'..."
az group create \
  --name "${RG_NAME}" \
  --location "${LOCATION}" \
  --output none

echo ">> Deploying Bicep template (${DEPLOYMENT_NAME})..."
az deployment group create \
  --resource-group "${RG_NAME}" \
  --name "${DEPLOYMENT_NAME}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters \
      location="${LOCATION}" \
      namePrefix="${NAME_PREFIX}" \
      sqlAdminLogin="${SQL_ADMIN_LOGIN}" \
      sqlAdminPassword="${SQL_ADMIN_PASSWORD}" \
  --output none

# --------------------------- Read outputs ----------------------------------
echo ">> Reading deployment outputs..."
OUTPUTS_JSON="$(az deployment group show \
  --resource-group "${RG_NAME}" \
  --name "${DEPLOYMENT_NAME}" \
  --query properties.outputs \
  --output json)"

get_out() { echo "${OUTPUTS_JSON}" | python -c "import sys,json;print(json.load(sys.stdin)['$1']['value'])"; }

WEB_APP_NAME="$(get_out webAppName)"
WEB_APP_HOST="$(get_out webAppDefaultHostname)"
SQL_FQDN="$(get_out sqlServerFqdn)"
SEARCH_ENDPOINT="$(get_out searchEndpoint)"
KEYVAULT_URI="$(get_out keyVaultUri)"
STORAGE_ACCOUNT="$(get_out storageAccountName)"

cat <<EOF

============================================================================
 Deployment complete: ${DEPLOYMENT_NAME}
============================================================================
 Web App name .............. ${WEB_APP_NAME}
 Web App URL ............... https://${WEB_APP_HOST}
 SQL Server FQDN ........... ${SQL_FQDN}
 AI Search endpoint ........ ${SEARCH_ENDPOINT}
 Key Vault URI ............. ${KEYVAULT_URI}
 Storage account ........... ${STORAGE_ACCOUNT}
============================================================================

 NEXT STEPS
 ----------
 1. Set the runtime secrets in Key Vault (see infra/bicep/README.md), e.g.:
        az keyvault secret set --vault-name "<vault>" \\
          --name GITHUB-TOKEN --value "<ghp_...>"
        az keyvault secret set --vault-name "<vault>" \\
          --name AZURE-SEARCH-ENDPOINT --value "${SEARCH_ENDPOINT}"
        az keyvault secret set --vault-name "<vault>" \\
          --name AZURE-KEYVAULT-URI --value "${KEYVAULT_URI}"
    (vault name = the segment between https:// and .vault.azure.net in the URI)

 2. Create the database schemas (NOT done by Bicep). Connect to
    ${SQL_FQDN} (database 'hca') and run the DDL:
        db/schema_facets_sim.sql      -- facets_sim schema (CMS MPFS data)
        db/schema_app_config.sql      -- app_config schema (cache/prompts/runs)
    e.g. with sqlcmd:
        sqlcmd -S "${SQL_FQDN}" -d hca -U "${SQL_ADMIN_LOGIN}" \\
          -P "\$SQL_ADMIN_PASSWORD" -i db/schema_facets_sim.sql
        sqlcmd -S "${SQL_FQDN}" -d hca -U "${SQL_ADMIN_LOGIN}" \\
          -P "\$SQL_ADMIN_PASSWORD" -i db/schema_app_config.sql

 3. Seed the CMS MPFS data:
        python db/seed_mpfs.py

 4. Restart the Web App so it picks up the Key Vault references:
        az webapp restart --name "${WEB_APP_NAME}" --resource-group "${RG_NAME}"
============================================================================
EOF
