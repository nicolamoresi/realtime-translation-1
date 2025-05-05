import { useEffect, useRef } from 'react'

interface Props {
  url: string
  sessionId: string
  onOpen?(): void
  onClose?(): void
  onError?(e: Event): void
  onMessage?(e: MessageEvent): void
  onConnected?(ws: WebSocket): void
}

/**
 * Lightweight wrapper that adds ?session_id=… to the URL.
 * Browsers cannot send custom headers in the WebSocket handshake,
 * therefore the backend must accept the query‑param in addition
 * to the X‑Session‑ID header for /ws/audio.
 */
export function SessionWebSocket({
  url,
  sessionId,
  onOpen,
  onClose,
  onError,
  onMessage,
  onConnected
}: Props) {
  const ref = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!sessionId) return

    const wsUrl = new URL(url)
    wsUrl.searchParams.set('session_id', sessionId) // <── carries the id
    const ws = new WebSocket(wsUrl.toString())
    ws.binaryType = 'arraybuffer'

    ws.onopen    = () => { onOpen?.();  onConnected?.(ws) }
    ws.onclose   = () => { onClose?.() }
    ws.onerror   = e  => { onError?.(e) }
    ws.onmessage = e  => { onMessage?.(e) }

    ref.current  = ws
    return () => { ws.close() }
  }, [url, sessionId, onOpen, onClose, onError, onMessage, onConnected])

  return null
}