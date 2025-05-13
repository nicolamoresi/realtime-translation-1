'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { CallComposite, createAzureCommunicationCallAdapter } from '@azure/communication-react'
import type { CallAdapter } from '@azure/communication-react'
import { Spinner } from '@fluentui/react-components'
import { API_BASE, getRoomToken } from '@/utils/api'
import { CommunicationTokenCredential, CommunicationGetTokenOptions } from '@azure/communication-common'
import type { AccessToken } from '@azure/core-auth'

// Custom CommunicationTokenCredential implementation
class CustomCommunicationTokenCredential implements CommunicationTokenCredential {
  private token: string;
  constructor(token: string) {
    this.token = token;
  }
  async getToken(_options?: CommunicationGetTokenOptions): Promise<AccessToken> {
    return {
      token: this.token,
      expiresOnTimestamp: Date.now() + 60 * 60 * 1000
    }
  }
  dispose(): void {
    // No-op for this simple implementation
  }
}

export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>()
  const [adapter, setAdapter] = useState<CallAdapter | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false;
    async function setupAdapter() {
      try {
        // Use the new API wrapper for room token
        const { token, userId } = await getRoomToken(roomId)
        const credential = new CustomCommunicationTokenCredential(token)
        const adapter = await createAzureCommunicationCallAdapter({
          userId,
          displayName: 'User', // You may want to set this dynamically
          credential,
          locator: { groupId: roomId }
        })
        if (!disposed) setAdapter(adapter)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to initialize room')
      }
    }
    setupAdapter()
    return () => {
      disposed = true
      if (adapter && adapter.dispose) adapter.dispose()
    }
    // eslint-disable-next-line
  }, [roomId])

  if (error) {
    return <div className="p-6 text-red-600">{error}</div>
  }
  if (!adapter) {
    return <div className="flex justify-center items-center h-full"><Spinner label="Joining room..." /></div>
  }

  return (
    <div style={{ height: '100vh', width: '100vw' }}>
      <CallComposite adapter={adapter} />
    </div>
  )
}