// ===========================================================================
// insights.bicep — Application Insights (workspace-based)
// ---------------------------------------------------------------------------
// Optional telemetry for the Web App. Workspace-based Application Insights
// requires a Log Analytics workspace; both have a free monthly ingestion grant
// (Log Analytics: 5 GB/mo free), so this stays within the spend target. The
// connection string is wired into the Web App's app settings in main.bicep via
// APPLICATIONINSIGHTS_CONNECTION_STRING.
// ===========================================================================

@description('Name of the Log Analytics workspace backing Application Insights.')
param logAnalyticsWorkspaceName string

@description('Name of the Application Insights component.')
param appInsightsName string

@description('Azure region for the telemetry resources.')
param location string

@description('Daily ingestion cap in GB to bound cost (Log Analytics free grant is 5 GB/mo).')
param dailyQuotaGb int = 1

@description('Tags applied to the telemetry resources.')
param tags object = {}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018' // Pay-as-you-go with the standard free monthly grant.
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb // Hard cap daily ingestion to control spend.
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id // Workspace-based (classic mode retired).
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

@description('Resource ID of the Application Insights component.')
output appInsightsId string = appInsights.id

@description('Application Insights connection string for the Web App.')
output connectionString string = appInsights.properties.ConnectionString

@description('Application Insights instrumentation key (legacy; connection string preferred).')
output instrumentationKey string = appInsights.properties.InstrumentationKey
