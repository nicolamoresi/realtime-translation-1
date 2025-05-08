// Azure Communication Services with Call Automation, VNet integration and Log Analytics

targetScope = 'resourceGroup'

@description('Azure region for Communication Services')
param location string

@description('Resource ID of the subnet used by ACS for VNET integration')
param infrastructureSubnetId string

@description('Log Analytics workspace ID for diagnostics')
param logAnalyticsWorkspaceId string

@description('Log Analytics workspace name for resource reference')
param logAnalyticsWorkspaceName string

@description('Deployment environment indicator (dev | test | prod)')
param envType string

@description('ACS resource name')
param communicationServiceName string = 'livetalk-acs'

@description('Enable Call Automation feature')
param enableCallAutomation bool = true

// Common tags to maintain consistency with other resources
var commonTags = {
  project: 'LiveTalk'
  environment: envType
}

// ────────────── Communication Services Resource ──────────────
resource communicationService 'Microsoft.Communication/communicationServices@2023-06-01-preview' = {
  name: communicationServiceName
  location: 'global' // ACS is a global resource
  properties: {
    dataLocation: 'United States'
    linkedDomains: []
  }
  tags: commonTags
}

// ────────────── Diagnostic Settings ──────────────
resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${communicationServiceName}-diagnostics'
  scope: communicationService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ────────────── Outputs ──────────────
output communicationServiceId string = communicationService.id
output communicationServiceEndpoint string = communicationService.properties.hostName
