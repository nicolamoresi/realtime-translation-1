// event.bicep – Azure Event Grid System Topic for LiveTalk
// Uses same VNet, location, tags, and identity conventions as ACA/ACS

targetScope = 'resourceGroup'

@description('Name of the Event Grid System Topic')
param name string

@description('Azure region for the Event Grid resource')
param location string

@description('Resource ID of the source for the system topic (e.g., a storage account, ACS, etc.)')
param source string

@description('The topic type for the system topic (e.g., Microsoft.Communication.CommunicationServices, Microsoft.Storage.StorageAccounts, etc.)')
param topicType string

@description('Tags to apply to the resource')
param tags object = {}

@description('Managed identity block for the system topic')
param identity object = {}

resource systemTopic 'Microsoft.EventGrid/systemTopics@2024-12-15-preview' = {
  name: name
  location: location
  tags: tags
  identity: identity
  properties: {
    source: source
    topicType: topicType
  }
}

output systemTopicId string = systemTopic.id
