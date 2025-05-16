import React, { useMemo } from 'react';
import { CallComposite, CallAdapter, useAzureCommunicationCallAdapter } from '@azure/communication-react';
import { AzureCommunicationTokenCredential, CommunicationUserIdentifier } from '@azure/communication-common';
import type { RoomCallLocator } from '@azure/communication-calling';


export type CallCompositeWrapperProps = {
  roomId: string;
  acsUserId: string;
  acsToken: string;
  displayName?: string;
};

const leaveCall = async (adapter: CallAdapter): Promise<void> => {
  await adapter.leaveCall().catch((e: unknown) => {
    console.error('Failed to leave call', e);
  });
};

export default function CallCompositeWrapper({
  roomId,
  acsUserId,
  acsToken,
  displayName = 'User'
}: CallCompositeWrapperProps) {

  const credential = useMemo(() => {
    try {
      return new AzureCommunicationTokenCredential(acsToken);
    } catch {
      console.error('Failed to construct token credential');
      return undefined;
    }
  }, [acsToken]);

  const roomLocator = useMemo<RoomCallLocator>(() => ({
    roomId
  }), [roomId]);

  const userIdObj = useMemo<CommunicationUserIdentifier>(() => ({
    communicationUserId: acsUserId
  }), [acsUserId]);

  if (!credential) {
    throw new Error('Azure Communication Token Credential is not defined.');
  }

  const adapter = useAzureCommunicationCallAdapter(
    {
      userId: userIdObj,
      displayName,
      credential,
      locator: roomLocator
    },
    undefined,
    leaveCall
  );

  if (!credential) {
    return <div className="p-6 text-red-600">Failed to construct credential. Provided token is malformed.</div>;
  }

  if (!adapter) {
    return <div className="p-6 text-blue-600">Joining room...</div>;
  }

  return (
    <div style={{ height: '100vh', width: '100vw' }}>
      <CallComposite adapter={adapter} />
    </div>
  );
}