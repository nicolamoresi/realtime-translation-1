//-----------------------------------------------
// main.bicep  – subscription‑scope entry point
//-----------------------------------------------
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param rgName string

@allowed([
  'eastus', 'eastus2', 'westus', 'westus2', 'westcentralus'
  'northeurope', 'francecentral', 'switzerlandnorth', 'switzerlandwest'
  'uksouth', 'australiaeast', 'eastasia', 'southeastasia'
  'centralindia', 'jioindiawest', 'japanwest', 'koreacentral'
])
param location string

@allowed([ 'dev', 'test', 'prod' ])
param environment string = 'dev'

param keyVaultName string = 'livetalk-kv'
param subscriptionId string = subscription().subscriptionId

@minLength(5)
@maxLength(50)
param acrName string = 'livetalkacr'
var   acrLoginServer = '${acrName}.azurecr.io'

param openAiAccountName       string = 'livetalk-openai'
param openAiCustomDomain      string = 'openai-livetalk'
param deployOpenAiAccount     bool   = true
param openAiRestore           bool   = false
param openAiModelDeployment   string = 'livetalk-4o'

@allowed([ 'gpt-4o', 'gpt-4o-mini', 'gpt-4o-realtime-preview' ])
param openAiModelName         string = 'gpt-4o'
param openAiModelVersion      string = '2024-11-20'
param openAiCapacity          int    = 80

param eventGridSystemTopicName string = 'livetalk-events'
param eventGridTopicType string = 'Microsoft.Communication.CommunicationServices'
param eventGridIdentity object = {} // or use a managed identity if needed


resource livetalkRG 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: rgName
  location: location
}

resource keyVault 'Microsoft.KeyVault/vaults@2021-06-01-preview' existing = {
  scope: livetalkRG
  name: keyVaultName
}

module vnetModule './modules/vnet.bicep' = {
  name: 'deployVnet'
  scope: livetalkRG
  params: {
    location: location
    envType: environment
    keyVaultReference: keyVault.name
  }
}

module logAnalyticsModule './modules/loga.bicep' = {
  name: 'deployLogAnalytics'
  scope: livetalkRG
  params: {
    workspaceName: 'livetalk-loganalytics'
    location: location
    retentionInDays: 30
    environment: environment
    keyVaultReference: keyVault.name
    subscriptionId: subscriptionId
  }
}

module acrModule './modules/acr.bicep' = {
  name: 'deployContainerRegistry'
  scope: livetalkRG
  params: {
    location: location
    environment: environment
    keyVaultReference: keyVault.name
    subscriptionId: subscriptionId
    acrName: acrName
    sku: 'Standard'
  }
}

module cosmosDbModule './modules/cosmos.bicep' = {
  name: 'deployCosmosDb'
  scope: livetalkRG
  params: {
    cosmosDbName: 'livetalk-cosmosdb'
    location: location
    resourceGroupLocation: livetalkRG.location
    environment: environment
    keyVaultReference: keyVault.name
    subscriptionId: subscriptionId
  }
}

module containerAppsEnvModule './modules/aca.bicep' = {
  name: 'deployContainerAppsEnv'
  scope: livetalkRG
  params: {
    location: location
    infrastructureSubnetId: vnetModule.outputs.containerAppsSubnetId
    logAnalyticsWorkspaceName: logAnalyticsModule.outputs.workspaceName
    envType: environment
    containerAppName: 'livetalk-api'
    containerAppImage: '${acrLoginServer}/api:latest'
    acrLoginServer: acrLoginServer
  }
}

module acsModule './modules/acs.bicep' = {
  name: 'deployCommunicationServices'
  scope: livetalkRG
  params: {
    location: location
    infrastructureSubnetId: vnetModule.outputs.containerAppsSubnetId
    logAnalyticsWorkspaceId: logAnalyticsModule.outputs.workspaceId
    logAnalyticsWorkspaceName: logAnalyticsModule.outputs.workspaceName
    envType: environment
    communicationServiceName: 'livetalk-acs'
    enableCallAutomation: true
  }
  dependsOn: [
    vnetModule
    logAnalyticsModule
  ]
}

module eventGridModule './modules/event.bicep' = {
  name: 'deployEventGridSystemTopic'
  scope: livetalkRG
  params: {
    name: eventGridSystemTopicName
    location: location
    source: acsModule.outputs.communicationServiceId
    topicType: eventGridTopicType
    tags: {
      project: 'LiveTalk'
      environment: environment
    }
    identity: eventGridIdentity
  }
  dependsOn: [
    acsModule
  ]
}

module openAiModule './modules/aoai.bicep' = {
  name: 'deployAzureOpenAI'
  scope: livetalkRG
  params: {
    aiServiceAccountName: openAiAccountName
    deployAccount: deployOpenAiAccount
    restore: openAiRestore
    location: location
    customSubDomainName: openAiCustomDomain
    subnetId: vnetModule.outputs.containerAppsSubnetId
    modelDeploymentName: openAiModelDeployment
    modelName: openAiModelName
    modelVersion: openAiModelVersion
    capacity: openAiCapacity
    tags: { project: 'LiveTalk', environment: environment }
  }
}

module staticWebApp './modules/staticwapp.bicep' = {
  name: 'deployStaticWebApp'
  scope: livetalkRG
  params: {
    location: location
    repositoryUrl: 'https://github.com/Azure-Samples/livetalk.git'
    environment: environment
    keyVaultReference: keyVault.name
  }
}

module storageAccount './modules/blob.bicep' = {
  name: 'deployStorageAccount'
  scope: livetalkRG
  params: {
    location: location
    environment: environment
    keyVaultReference: keyVault.name
    subscriptionId: subscriptionId
  }
}
