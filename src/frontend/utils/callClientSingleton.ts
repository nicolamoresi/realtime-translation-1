import { CallClient, CallAgent } from '@azure/communication-calling';

let callClient: CallClient | null = null;
const callAgentMap: Record<string, CallAgent> = {};

export function getCallClient() {
  if (!callClient) {
    callClient = new CallClient();
  }
  return callClient;
}

export function getCallAgent(identity: string) {
  return callAgentMap[identity];
}

export function setCallAgent(identity: string, agent: CallAgent) {
  callAgentMap[identity] = agent;
}

export async function disposeCallAgent(identity: string) {
  if (callAgentMap[identity]) {
    try {
      await callAgentMap[identity].dispose();
    } catch {}
    delete callAgentMap[identity];
  }
}
