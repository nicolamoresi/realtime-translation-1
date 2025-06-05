// Single Bicep file to deploy Azure Communication Services with VNet integration and Log Analytics

targetScope = 'resourceGroup'

@description('Azure region for Communication Services')
param location string

@description('Resource ID of the subnet used by ACS for VNET integration')
param infrastructureSubnetId string

@description('Log Analytics workspace resource ID for diagnostics')
param logAnalyticsWorkspaceId string

@description('Log Analytics workspace name for resource reference')
param logAnalyticsWorkspaceName string

@description('Deployment environment indicator (dev | test | prod)')
@allowed([ 'dev', 'test', 'prod' ])
param envType string = 'dev'

@description('ACS resource name')
param communicationServiceName string = 'livetalk-acs'

@description('Enable Call Automation feature')
param enableCallAutomation bool = true

@description('Tags to apply to the Communication Services resource')
param tags object = {
  project    : 'LiveTalk'
  environment: envType
}

//
// Azure Communication Services
//
resource communicationService 'Microsoft.Communication/communicationServices@2024-09-01-preview' = {
  name     : communicationServiceName
  location : 'global'
  tags     : tags
  properties: {
    dataLocation : 'United States'
    linkedDomains: []
  }
}

//
// Diagnostic Settings for ACS
//
resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name   : '${communicationServiceName}-diagnostics'
  scope  : communicationService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: [
      {
        category: 'AllMetrics'
        enabled : true
      }
    ]
  }
}


output communicationServiceId       string = communicationService.id
output communicationServiceEndpoint string = communicationService.properties.hostName
