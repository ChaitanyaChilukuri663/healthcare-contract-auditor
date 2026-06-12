// ===========================================================================
// keyvault.bicep — Azure Key Vault (standard SKU, RBAC authorization)
// ---------------------------------------------------------------------------
// Holds the application secrets the Web App reads at runtime via
// @Microsoft.KeyVault(...) app-setting references:
//   GITHUB_TOKEN, AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY,
//   AZURE_SQL_CONNECTION_STRING, AZURE_BLOB_CONNECTION_STRING, AZURE_KEYVAULT_URI
// RBAC authorization is enabled (enableRbacAuthorization = true) so access is
// granted via the "Key Vault Secrets User" role assignment in main.bicep
// rather than legacy access policies.
//
// NOTE: This module intentionally does NOT create the secret *values* — secrets
// are populated post-deploy with `az keyvault secret set` (see README.md), so
// that real tokens never live in the IaC or deployment history.
// ===========================================================================

@description('Globally-unique Key Vault name (3-24 chars, alphanumeric and hyphens).')
param keyVaultName string

@description('Azure region for the Key Vault.')
param location string

@description('Tenant ID that owns the Key Vault.')
param tenantId string = subscription().tenantId

@description('Tags applied to the Key Vault.')
param tags object = {}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: tenantId
    enableRbacAuthorization: true // RBAC instead of access policies.
    enableSoftDelete: true
    softDeleteRetentionInDays: 7 // Minimum retention to keep cleanup cheap/fast.
    enablePurgeProtection: null // Leave off so the vault can be fully purged in a POC.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

@description('Resource ID of the Key Vault (used for RBAC role assignments).')
output keyVaultId string = keyVault.id

@description('Name of the Key Vault.')
output keyVaultName string = keyVault.name

@description('Vault URI, e.g. https://<vault>.vault.azure.net/.')
output keyVaultUri string = keyVault.properties.vaultUri
