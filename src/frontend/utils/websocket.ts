// utils/websocket.ts

export interface WSMessage {
  transcript?: string
  translated?: string
  video?: string        // base64 video frame
  // audio chunks are delivered via the onBinary callback
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"

export function createWebSocket(
  path: string,
  token: string,
  onText: (msg: WSMessage) => void,
  onBinary?: (data: ArrayBuffer) => void
): WebSocket {
  const url = new URL(path, API_BASE)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('token', token)

  const ws = new WebSocket(url.toString())
  ws.binaryType = 'arraybuffer'

  ws.onmessage = (ev: MessageEvent<string | ArrayBuffer>) => {
    if (typeof ev.data === 'string') {
      try {
        const msg = JSON.parse(ev.data) as WSMessage
        onText(msg)
      } catch {
        // ignore non-JSON text frames
      }
    } else if (ev.data instanceof ArrayBuffer && onBinary) {
      onBinary(ev.data)
    }
  }

  return ws
}
