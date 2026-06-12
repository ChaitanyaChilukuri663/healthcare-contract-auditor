// ===========================================================================
// storage.bicep — Azure Storage Account + blob container for contract PDFs
// ---------------------------------------------------------------------------
// Standard_LRS (cheapest redundancy). One blob container "contracts" holds the
// provider-contract PDFs that pdf_ingest.py uploads before indexing them into
// Azure AI Search. The Web App reads/writes blobs via its managed identity
// (Storage Blob Data Contributor role granted in main.bicep) and/or a
// connection string surfaced through Key Vault.
// ===========================================================================

@description('Globally-unique storage account name (3-24 chars, lowercase alphanumeric).')
param storageAccountName string

@description('Azure region for the storage account.')
param location string

@description('Name of the blob container that holds contract PDFs.')
param containerName string = 'contracts'

@description('Tags applied to the storage account.')
param tags object = {}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS' // Cheapest: locally redundant storage.
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false // Private; access via managed identity / SAS only.
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource contractsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

@description('Resource ID of the storage account (used for RBAC role assignments).')
output storageAccountId string = storageAccount.id

@description('Name of the storage account.')
output storageAccountName string = storageAccount.name

@description('Primary blob service endpoint, e.g. https://<acct>.blob.core.windows.net/.')
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob

@description('Name of the contracts blob container.')
output containerName string = contractsContainer.name
