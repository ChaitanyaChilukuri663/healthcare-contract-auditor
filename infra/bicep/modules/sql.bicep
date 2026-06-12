// ===========================================================================
// sql.bicep — Azure SQL logical server + single database
// ---------------------------------------------------------------------------
// One logical server hosts one database. The application's two logical
// schemas — facets_sim (CMS MPFS fee data) and app_config (cache, prompts,
// audit runs) — live INSIDE this single database and are created by SQL DDL
// (db/schema_facets_sim.sql, db/schema_app_config.sql), NOT by Bicep. This
// module therefore only provisions server + database + firewall.
//
// Tier selection (see `useFreeServerless` param):
//   - General Purpose Serverless with the "Free offer" (useGPServerlessFreeOffer
//     = true, the default): uses GP_S_Gen5_2 with autoPause and the
//     `freeLimitExhaustionBehavior` property that caps the database at the
//     monthly free vCore-seconds + 32 GB. This keeps spend at ~$0 while the
//     free allowance lasts and AutoPause to $0 when idle. ONE free database is
//     allowed per subscription; deploying a second will fail.
//   - Basic (useGPServerlessFreeOffer = false): the classic ~$5/mo DTU tier
//     fallback if the free offer is unavailable in your subscription/region.
// ===========================================================================

@description('Globally-unique Azure SQL logical server name (lowercase, 1-63 chars).')
param sqlServerName string

@description('Name of the single application database.')
param databaseName string = 'hca'

@description('Azure region for the SQL server and database.')
param location string

@description('SQL administrator login name.')
param administratorLogin string

@description('SQL administrator password.')
@secure()
param administratorPassword string

@description('When true, use General Purpose Serverless with the free offer; when false, fall back to the Basic DTU tier (~$5/mo).')
param useGPServerlessFreeOffer bool = true

@description('Tags applied to the SQL resources.')
param tags object = {}

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  tags: tags
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// --- General Purpose Serverless w/ Free offer ------------------------------
// Capped to the free monthly allowance; AutoPause after 60 min idle drops
// compute cost to $0. `freeLimitExhaustionBehavior: AutoPause` pauses the DB
// (rather than billing) once the free vCore-seconds are spent.
resource dbServerlessFree 'Microsoft.Sql/servers/databases@2023-08-01-preview' = if (useGPServerlessFreeOffer) {
  parent: sqlServer
  name: databaseName
  location: location
  tags: tags
  sku: {
    name: 'GP_S_Gen5_2' // General Purpose, Serverless, Gen5, up to 2 vCores.
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 2
  }
  properties: {
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    maxSizeBytes: 34359738368 // 32 GB (free offer storage cap).
    autoPauseDelay: 60 // Pause after 60 min idle → $0 compute when not in use.
    minCapacity: json('0.5') // Minimum serverless vCores.
    zoneRedundant: false
    useFreeLimit: true
    freeLimitExhaustionBehavior: 'AutoPause' // Stay at $0: pause when free allowance is exhausted.
  }
}

// --- Basic DTU tier fallback -----------------------------------------------
// Used only when the free serverless offer is disabled/unavailable.
resource dbBasic 'Microsoft.Sql/servers/databases@2023-08-01-preview' = if (!useGPServerlessFreeOffer) {
  parent: sqlServer
  name: databaseName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
    tier: 'Basic'
    capacity: 5 // 5 DTU.
  }
  properties: {
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    maxSizeBytes: 2147483648 // 2 GB (Basic tier max).
    zoneRedundant: false
  }
}

// Allow other Azure services (e.g. the App Service Web App) to reach the
// server. The 0.0.0.0 sentinel rule is the documented "Allow Azure services"
// toggle; it does not open the server to the public internet.
resource allowAzureServices 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

@description('Resource ID of the SQL logical server.')
output sqlServerId string = sqlServer.id

@description('Name of the SQL logical server.')
output sqlServerName string = sqlServer.name

@description('Fully-qualified domain name of the SQL server, e.g. <server>.database.windows.net.')
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName

@description('Name of the application database.')
output databaseName string = databaseName
