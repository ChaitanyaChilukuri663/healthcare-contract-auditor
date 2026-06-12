// ===========================================================================
// search.bicep — Azure AI Search (free SKU)
// ---------------------------------------------------------------------------
// Vector + keyword store for the RAG pipeline. The free SKU is intentional for
// this portfolio POC; its hard caps are:
//   - 50 MB total storage
//   - 3 indexes
//   - 1 replica / 1 partition (no SLA, shared infrastructure)
// pdf_ingest.py creates and populates the contract index here. The Web App
// authenticates with its managed identity (Search Index Data Contributor role
// granted in main.bicep) and/or an admin key surfaced through Key Vault.
// ===========================================================================

@description('Globally-unique Azure AI Search service name (2-60 chars, lowercase, hyphens allowed but not leading/trailing/consecutive).')
param searchServiceName string

@description('Azure region for the search service.')
param location string

@description('Tags applied to the search service.')
param tags object = {}

resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: 'free' // 50 MB / 3 indexes — sufficient for the POC corpus.
  }
  properties: {
    replicaCount: 1 // Free tier supports exactly 1 replica and 1 partition.
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    // Both API keys and Azure AD (RBAC) auth are allowed so the Web App can use
    // its managed identity while admin keys remain available for tooling.
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

@description('Resource ID of the search service (used for RBAC role assignments).')
output searchServiceId string = searchService.id

@description('Name of the search service.')
output searchServiceName string = searchService.name

@description('Search service endpoint, e.g. https://<name>.search.windows.net.')
output searchEndpoint string = 'https://${searchService.name}.search.windows.net'
