'use client'

/*
  Mic-only real-time translation demo
  ───────────────────────────────────
  • POST /chat/start                – create session
  • POST /chat/message {audio:b64}  – send audio, receive {reply, audio}
  • POST /chat/stop                 – cleanup
*/

import { useEffect, useState, useRef } from 'react'
import { useParams } from 'next/navigation'
import {
  getAnonymousAccess,
  startChatSession,
  sendChatMessage,
  stopChatSession
} from '@/utils/api'

import { encodeWav } from '@/utils/wav'

interface ChatLine { role: 'assistant' | 'user'; content: string }

export default function Simulator() {
  /* ─ state ─ */
  const { roomId } = useParams<{ roomId: string }>()
  const [token, setTok]   = useState<string | null>(null)
  const [sid,   setSid]   = useState<string | null>(null)
  const [chat,  setChat]  = useState<ChatLine[]>([])
  const [status,setStats] = useState('Connecting …')
  const [err,   setErr]   = useState<string | null>(null)
  const [rec,   setRec]   = useState(false)

  /* ─ refs ─ */
  const media  = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const audioR = useRef<HTMLAudioElement | null>(null)

  /* auth */
  useEffect(() => {
    (async () => {
      try {
        const anon = new URLSearchParams(location.search).get('anonymous') === 'true'
        const t = anon ? (await getAnonymousAccess(roomId)).access_token
                       : localStorage.getItem('token')
        if (!t) throw new Error('no token')
        if (anon) localStorage.setItem('token', t)
        setTok(t)
      } catch {
        setErr('Authentication failed')
      }
    })()
  }, [roomId])

  /* create session */
  useEffect(() => {
    if (!token) return
    ;(async () => {
      try {
        const { session_id, message } = await startChatSession(token)
        setSid(session_id)
        setChat([{ role: 'assistant', content: message }])
        setStats('Ready')
      } catch {
        setErr('Failed to create session')
      }
    })()
  }, [token])

  /* cleanup */
  useEffect(() => {
    return () => {
      if (sid) stopChatSession(sid).catch(() => {})
    }
  }, [sid])

  /* mic helpers */
  async function startRec() {
    if (rec || !sid) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      media.current = mr

      mr.ondataavailable = (e: BlobEvent) => { if (e.data.size) chunks.current.push(e.data) }

      mr.onstop = async () => {
        const blob = new Blob(chunks.current, { type: 'audio/webm' })
        chunks.current = []
        const b64 = await blobToB64(blob)
        try {
          const rsp = await sendChatMessage(sid!, undefined, b64)

          // assistant reply
          if (rsp.reply) {
            setChat(c => [...c, { role: 'assistant', content: rsp.reply }])
          }

          // assistant audio
          if (rsp.audio_base64 && audioR.current) {
            try {
              // ➊ encoda PCM16 -> WAV bytes
              const wavBytes = encodeWav(rsp.audio_base64, 24000 /* Hz */)

              // ➋ copia in un buffer "sicuro" (non SharedArrayBuffer)
              const copied = new Uint8Array(wavBytes)            // nuova view con nuovo ArrayBuffer
              const ab: ArrayBuffer = copied.buffer.slice(0)     // ArrayBuffer puro

              // ➌ crea Blob e URL
              const url = URL.createObjectURL(new Blob([ab], { type: 'audio/wav' }))
              audioR.current.src = url
              await audioR.current.play().catch(() => {})
            } catch {
              // ignore bad audio
            }
          }
        } catch {
          // ignore per-chunk errors
        }

        if (rec) mr.start()
      }

      mr.start()
      setRec(true)
      setStats('Recording …')
    } catch {
      setErr('Mic permission denied')
    }
  }

  const stopRec = () => {
    setRec(false)
    setStats('Ready')
    media.current?.stop()
    media.current?.stream.getTracks().forEach(t => t.stop())
    media.current = null
  }
  const toggleRec = () => (rec ? stopRec() : startRec())

  /* util */
  const blobToB64 = (b: Blob) =>
    new Promise<string>(res => {
      const fr = new FileReader()
      fr.onload = () => res((fr.result as string).split(',')[1])
      fr.readAsDataURL(b)
    })

  /* UI */
  if (err) return <p className="p-6 text-red-600">{err}</p>

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-bold">Session {roomId}</h1>
      <p>Status: {status}</p>

      <div className="space-y-4 max-h-96 overflow-auto border p-4 rounded bg-gray-50">
        {chat.map((m, i) => (
          <p key={i} className="text-gray-800">
            <span className="font-medium">{m.role === 'user' ? 'You: ' : 'Assistant: '}</span>
            {m.content}
          </p>
        ))}
      </div>

      {/* audio player for assistant voice */}
      <audio ref={audioR} hidden />

      {/* mic control */}
      <button
        onClick={toggleRec}
        className={`px-6 py-3 rounded-full text-white font-bold ${rec ? 'bg-red-600' : 'bg-green-600'}`}
        disabled={!sid}
      >
        {rec ? 'Stop Mic' : 'Start Mic'}
      </button>
    </div>
  )
}
