targetScope = 'resourceGroup'

@description('Name of the Event Grid System Topic')
param name string

@description('Azure region for the Event Grid resource')
param location string

@description('Resource ID of the source for the system topic (e.g., ACS)')
param source string

@description('The topic type for the system topic (e.g., Microsoft.Communication.CommunicationServices)')
param topicType string

@description('Tags to apply to the resource')
param tags object

@description('Managed identity block for the system topic')
param identity object

resource systemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' = {
  name:     name
  location: location
  tags:     tags
  identity: identity
  properties: {
    source:    source
    topicType: topicType
  }
}

resource subscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2025-02-15' = {
  parent: systemTopic
  name:   'localConnection'
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        maxEventsPerBatch:            1
        preferredBatchSizeInKilobytes: 64
        minimumTlsVersionAllowed:      '1.1'
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Communication.IncomingCall'
        'Microsoft.Communication.CallStarted'
      ]
      enableAdvancedFilteringOnArrays: true
    }
    labels:             []
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: {
      maxDeliveryAttempts:       30
      eventTimeToLiveInMinutes: 1440
    }
  }
}
