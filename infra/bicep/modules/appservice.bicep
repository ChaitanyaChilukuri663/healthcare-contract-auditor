// ===========================================================================
// appservice.bicep — Linux App Service Plan (F1 Free) + Python Web App
// ---------------------------------------------------------------------------
// Hosts the FastAPI app. The plan is Linux on the F1 (Free) SKU. The Web App:
//   - runs the Python 3.12 runtime image (linuxFxVersion 'PYTHON|3.12').
//     NOTE: the project targets requires-python >=3.12 and the code is
//     3.13-compatible, but Azure's published App Service runtime image tag is
//     PYTHON|3.12 — there is no PYTHON|3.13 tag, so 3.12 is the correct value.
//   - has a system-assigned managed identity (used for Key Vault, Blob, and
//     AI Search RBAC role assignments wired up in main.bicep).
//   - receives its full app-settings array from main.bicep (which builds the
//     @Microsoft.KeyVault(...) secret references), so this module stays
//     agnostic about secret names.
//
// Caveat: F1 is Free but has hard limits — 60 CPU-min/day, 1 GB RAM, no
// "Always On" (set explicitly to false; enabling it is unsupported on F1).
// ===========================================================================

@description('Name of the Linux App Service Plan.')
param appServicePlanName string

@description('Globally-unique Web App name.')
param webAppName string

@description('Azure region for the plan and web app.')
param location string

@description('Linux runtime stack for the web app. Azure publishes PYTHON|3.12 (no 3.13 image tag exists).')
param linuxFxVersion string = 'PYTHON|3.12'

@description('App settings name/value pairs (built by main.bicep, including Key Vault references).')
param appSettings array = []

@description('Tags applied to the App Service resources.')
param tags object = {}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  tags: tags
  sku: {
    name: 'F1' // Free tier.
    tier: 'Free'
    capacity: 1
  }
  kind: 'linux'
  properties: {
    reserved: true // Required for Linux plans.
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  tags: tags
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned' // Managed identity for Key Vault / Blob / Search RBAC.
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: linuxFxVersion
      alwaysOn: false // MUST be false on F1; Always On is unsupported on Free.
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      // Build the app from source on deploy (Oryx) so `uv`/pip can install deps.
      // FastAPI is served by Uvicorn; adjust the module path if app.py moves.
      appCommandLine: 'python -m uvicorn app:app --host 0.0.0.0 --port 8000'
      appSettings: appSettings
    }
  }
}

@description('Resource ID of the Web App.')
output webAppId string = webApp.id

@description('Name of the Web App.')
output webAppName string = webApp.name

@description('Default hostname of the Web App (without scheme).')
output webAppDefaultHostname string = webApp.properties.defaultHostName

@description('Principal (object) ID of the Web App system-assigned managed identity.')
output webAppPrincipalId string = webApp.identity.principalId
