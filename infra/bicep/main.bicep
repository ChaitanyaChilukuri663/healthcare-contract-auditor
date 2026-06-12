// ===========================================================================
// main.bicep — healthcare-contract-auditor Azure infrastructure (top level)
// ---------------------------------------------------------------------------
// Deploys the full Free/cheapest-tier stack for the FastAPI portfolio app:
//   - Azure SQL logical server + single database (GP Serverless Free offer,
//     Basic fallback). The facets_sim / app_config schemas are created later
//     by SQL DDL, not here.
//   - Azure AI Search (free SKU).
//   - Storage account (Standard_LRS) + "contracts" blob container.
//   - Key Vault (standard, RBAC authorization).
//   - App Service Plan (Linux F1) + Python 3.12 Web App.
//   - Application Insights (workspace-based, capped ingestion).
//
// It also:
//   - wires the Web App's app settings to @Microsoft.KeyVault(...) references
//     for the runtime secrets (GITHUB_TOKEN, search/SQL/blob/vault config).
//   - grants the Web App's managed identity the RBAC roles it needs
//     (Key Vault Secrets User, Storage Blob Data Contributor, Search Index
//     Data Contributor).
//
// Target spend: < $5/mo on the free/cheapest tiers. Set a Cost Management
// budget alert before deploying (see deploy.sh header).
// ===========================================================================

targetScope = 'resourceGroup'

// --------------------------- Parameters ------------------------------------

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short prefix used to name resources (lowercase letters/digits).')
@minLength(2)
@maxLength(8)
param namePrefix string = 'hca'

@description('Azure SQL administrator login name.')
param sqlAdminLogin string

@description('Azure SQL administrator password.')
@secure()
param sqlAdminPassword string

@description('LLM provider selection surfaced to the app as LLM_PROVIDER. Default github per the project abstraction.')
param llmProvider string = 'github'

@description('Use the Azure SQL GP Serverless free offer (true) or fall back to Basic DTU (~$5/mo) (false).')
param useGPServerlessFreeOffer bool = true

@description('Deploy Application Insights + Log Analytics telemetry (optional).')
param deployAppInsights bool = true

@description('Tags applied to every resource.')
param tags object = {
  project: 'healthcare-contract-auditor'
  environment: 'poc'
  costCenter: 'portfolio'
}

// --------------------------- Naming ----------------------------------------
// A short, deterministic suffix derived from the resource group id keeps
// globally-unique names (storage, search, key vault, SQL server, web app)
// stable across redeploys while avoiding collisions.

var uniqueSuffix = uniqueString(resourceGroup().id)
var shortSuffix = substring(uniqueSuffix, 0, 6)

// Storage account: 3-24 chars, lowercase alphanumeric ONLY (no hyphens).
var storageAccountName = toLower('${namePrefix}st${shortSuffix}')
// Key Vault: 3-24 chars, alphanumeric + hyphens.
var keyVaultName = toLower('${namePrefix}-kv-${shortSuffix}')
// AI Search: 2-60 chars, lowercase, hyphens allowed (not leading/trailing).
var searchServiceName = toLower('${namePrefix}-search-${shortSuffix}')
// SQL logical server: lowercase, 1-63 chars.
var sqlServerName = toLower('${namePrefix}-sql-${shortSuffix}')
// Web App / Plan.
var webAppName = toLower('${namePrefix}-app-${shortSuffix}')
var appServicePlanName = toLower('${namePrefix}-plan-${shortSuffix}')
// Telemetry.
var appInsightsName = toLower('${namePrefix}-ai-${shortSuffix}')
var logAnalyticsWorkspaceName = toLower('${namePrefix}-law-${shortSuffix}')

var databaseName = 'hca'
var blobContainerName = 'contracts'

// Built-in RBAC role definition IDs (stable GUIDs across all tenants).
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'

// --------------------------- Modules ---------------------------------------

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    storageAccountName: storageAccountName
    location: location
    containerName: blobContainerName
    tags: tags
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    keyVaultName: keyVaultName
    location: location
    tags: tags
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    searchServiceName: searchServiceName
    location: location
    tags: tags
  }
}

module sql 'modules/sql.bicep' = {
  name: 'sql'
  params: {
    sqlServerName: sqlServerName
    databaseName: databaseName
    location: location
    administratorLogin: sqlAdminLogin
    administratorPassword: sqlAdminPassword
    useGPServerlessFreeOffer: useGPServerlessFreeOffer
    tags: tags
  }
}

module insights 'modules/insights.bicep' = if (deployAppInsights) {
  name: 'insights'
  params: {
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    appInsightsName: appInsightsName
    location: location
    tags: tags
  }
}

// --------------------------- App settings ----------------------------------
// Runtime secrets are referenced from Key Vault using @Microsoft.KeyVault(...)
// syntax. The App Service resolves these at startup using the Web App's
// managed identity (granted Key Vault Secrets User below). The secret *values*
// are NOT created here — they are set post-deploy with `az keyvault secret set`
// (see infra/bicep/README.md). Until then these references resolve to empty.
//
// SecretUri form is used so the reference is unambiguous; the vault URI comes
// from the keyvault module output.
var kvUri = keyVault.outputs.keyVaultUri // e.g. https://<vault>.vault.azure.net/

func kvRef(uri string, secretName string) string =>
  '@Microsoft.KeyVault(SecretUri=${uri}secrets/${secretName})'

var baseAppSettings = [
  // Oryx build settings so the platform installs requirements on deploy.
  {
    name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
    value: 'true'
  }
  {
    name: 'ENABLE_ORYX_BUILD'
    value: 'true'
  }
  // Non-secret application config.
  {
    name: 'LLM_PROVIDER'
    value: llmProvider
  }
  {
    name: 'APP_NAME'
    value: 'healthcare-contract-auditor'
  }
  // Secret references resolved from Key Vault via managed identity.
  {
    name: 'GITHUB_TOKEN'
    value: kvRef(kvUri, 'GITHUB-TOKEN')
  }
  {
    name: 'AZURE_SEARCH_ENDPOINT'
    value: kvRef(kvUri, 'AZURE-SEARCH-ENDPOINT')
  }
  {
    name: 'AZURE_SEARCH_KEY'
    value: kvRef(kvUri, 'AZURE-SEARCH-KEY')
  }
  {
    name: 'AZURE_SQL_CONNECTION_STRING'
    value: kvRef(kvUri, 'AZURE-SQL-CONNECTION-STRING')
  }
  {
    name: 'AZURE_BLOB_CONNECTION_STRING'
    value: kvRef(kvUri, 'AZURE-BLOB-CONNECTION-STRING')
  }
  {
    name: 'AZURE_KEYVAULT_URI'
    value: kvRef(kvUri, 'AZURE-KEYVAULT-URI')
  }
]

// Append the App Insights connection string only when telemetry is deployed.
var appInsightsSettings = deployAppInsights
  ? [
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: insights.outputs.connectionString
      }
      {
        name: 'ApplicationInsightsAgent_EXTENSION_VERSION'
        value: '~3'
      }
    ]
  : []

var webAppSettings = concat(baseAppSettings, appInsightsSettings)

module appService 'modules/appservice.bicep' = {
  name: 'appservice'
  params: {
    appServicePlanName: appServicePlanName
    webAppName: webAppName
    location: location
    linuxFxVersion: 'PYTHON|3.12' // 3.13-compatible code; Azure's image tag is PYTHON|3.12.
    appSettings: webAppSettings
    tags: tags
  }
}

// --------------------------- RBAC role assignments -------------------------
// Grant the Web App's system-assigned managed identity least-privilege data
// roles. role-assignment names must be deterministic GUIDs scoped to the
// (resource, principal, role) triple so redeploys are idempotent.

// Key Vault Secrets User → lets the Web App read secret values for the
// @Microsoft.KeyVault(...) app-setting references. Scoped to the vault.
resource kvSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.outputs.keyVaultId, appService.outputs.webAppPrincipalId, keyVaultSecretsUserRoleId)
  scope: keyVaultExisting
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: appService.outputs.webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Blob Data Contributor → read/write contract PDFs in blob storage.
resource blobContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.outputs.storageAccountId, appService.outputs.webAppPrincipalId, storageBlobDataContributorRoleId)
  scope: storageExisting
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: appService.outputs.webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Search Index Data Contributor → create/populate/query AI Search indexes.
resource searchContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.outputs.searchServiceId, appService.outputs.webAppPrincipalId, searchIndexDataContributorRoleId)
  scope: searchExisting
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: appService.outputs.webAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Existing-resource handles so role assignments can target the correct scope.
// (Role assignments must be scoped to a resource symbol, not a module output.)
resource keyVaultExisting 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource storageExisting 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource searchExisting 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchServiceName
}

// --------------------------- Outputs ---------------------------------------

@description('Name of the deployed Web App.')
output webAppName string = appService.outputs.webAppName

@description('Default hostname of the Web App (without scheme).')
output webAppDefaultHostname string = appService.outputs.webAppDefaultHostname

@description('Fully-qualified domain name of the Azure SQL server.')
output sqlServerFqdn string = sql.outputs.sqlServerFqdn

@description('Azure AI Search endpoint URL.')
output searchEndpoint string = search.outputs.searchEndpoint

@description('Key Vault URI for storing/reading application secrets.')
output keyVaultUri string = keyVault.outputs.keyVaultUri

@description('Name of the storage account holding contract PDFs.')
output storageAccountName string = storage.outputs.storageAccountName
