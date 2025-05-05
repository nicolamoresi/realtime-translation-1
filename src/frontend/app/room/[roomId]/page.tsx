'use client'

/*
  Audio‑only real‑time translation client (AudioWorklet‑only)
  -----------------------------------------------------------
  • Anonymous or signed‑in token
  • ONE voice WebSocket
  • Mic capture with AudioWorkletNode (no ScriptProcessor fallback)
  • 7 s silence auto‑stop
  • Live playback through <audio>
  • Small traffic monitor
*/

import { useEffect, useRef, useState } from 'react'
import { useParams }                      from 'next/navigation'
import { API_BASE, getAnonymousAccess }   from '@/utils/api'

interface Stats { out: number; in: number }

export default function Simulator() {
  /* ────────── state ────────── */
  const { roomId } = useParams<{ roomId: string }>()
  const [token,  setToken]  = useState<string | null>(null)
  const [error,  setError]  = useState<string | null>(null)
  const [status, setStatus] = useState('Connecting …')
  const [micOn,  setMicOn]  = useState(false)
  const [talk ,  setTalk ]  = useState(false)
  const [stats,  setStats]  = useState<Stats>({ out: 0, in: 0 })

  /* ────────── refs ─────────── */
  const wsRef     = useRef<WebSocket | null>(null)
  const ctxRef    = useRef<AudioContext | null>(null)
  const nodeRef   = useRef<AudioWorkletNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const micFlag   = useRef(false)
  const lastAct   = useRef<number>(Date.now())
  const timerRef  = useRef<number | null>(null)
  const audioElm  = useRef<HTMLAudioElement | null>(null)

  useEffect(() => { micFlag.current = micOn }, [micOn])

  /* ────────── auth (anon) ───── */
  useEffect(() => {
    const anon = new URLSearchParams(location.search).get('anonymous') === 'true'
    ;(async () => {
      try {
        const tk = anon
          ? (await getAnonymousAccess(roomId)).access_token
          : localStorage.getItem('token')
        if (!tk) throw new Error('no token')
        if (anon) localStorage.setItem('token', tk)
        setToken(tk)
      } catch { setError('Authentication failed') }
    })()
  }, [roomId])

  /* ───── open / close WS ───── */
  useEffect(() => {
    if (!token) return
    const ws = new WebSocket(
      `${API_BASE.replace(/^http/, 'ws')}/ws/voice/${roomId}?token=${token}&audio_only=true`
    )
    ws.binaryType = 'arraybuffer'
    ws.onopen  = () => setStatus('Connected')
    ws.onclose = () => setStatus('Disconnected')
    ws.onerror = () => setError('Voice WebSocket error')
    ws.onmessage = ev => {
      if (!(ev.data instanceof ArrayBuffer)) return
      setStats(s => ({ ...s, in: s.in + ev.data.byteLength }))
      if (audioElm.current) {
        const url = URL.createObjectURL(new Blob([ev.data], { type: 'audio/wav' }))
        audioElm.current.src = url
        audioElm.current.play().catch(() => {})
      }
    }
    wsRef.current = ws
    return () => ws.close()
  }, [token, roomId])

  /* ───── mic helpers ───── */
  async function startMic() {
    if (micOn || wsRef.current?.readyState !== WebSocket.OPEN) return

    /* Ensure AudioWorklet support */
    const workletSupported = 'AudioWorklet' in window
    if (!workletSupported) {
      setError('AudioWorklet not supported by this browser')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const AudioContextConstructor = window.AudioContext || ((window as unknown) as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioContextConstructor();
      ctxRef.current = ctx
      const src = ctx.createMediaStreamSource(stream)

      /* inlined worklet */
      const blob = new Blob(
        [`
          class P extends AudioWorkletProcessor {
            process(i){
              const c=i[0][0];
              if(!c) return true;
              let m=0; for(const v of c) m+=Math.abs(v);
              const act=m/c.length>0.01;
              this.port.postMessage({act,buf:c.buffer},[c.buffer]);
              return true;
            }
          } registerProcessor('p',P);
        `],
        { type: 'application/javascript' }
      )

      await ctx.audioWorklet.addModule(URL.createObjectURL(blob))

      const node = new AudioWorkletNode(ctx, 'p', { numberOfOutputs: 0 })
      node.port.onmessage = ({ data }) => {
        if (!micFlag.current || !data.act) return
        lastAct.current = Date.now()
        wsRef.current!.send(data.buf)
        setStats(s => ({ ...s, out: s.out + (data.buf as ArrayBuffer).byteLength }))
      }
      src.connect(node)
      nodeRef.current = node

      timerRef.current = window.setInterval(() => {
        if (Date.now() - lastAct.current > 7000) toggleMic()
      }, 1000)

      setMicOn(true)
      setTalk(true)
    } catch {
      setError('Microphone permission denied or AudioWorklet init failed')
    }
  }

  function stopMic() {
    setMicOn(false); setTalk(false)
    if (timerRef.current !== null) clearInterval(timerRef.current)
    nodeRef.current?.disconnect()
    ctxRef.current?.close()
    streamRef.current?.getTracks().forEach(t => t.stop())
    nodeRef.current = null
    ctxRef.current  = null
    streamRef.current = null
  }

  const toggleMic = () => (micOn ? stopMic() : startMic())

  /* ───── UI ───── */
  if (error) return <p className="p-6 text-red-600">{error}</p>

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold">Room {roomId}</h1>
      <p>Status: {status}</p>

      {/* traffic */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="p-2 bg-gray-100 rounded">
          <p className="font-medium">Out</p>
          {(stats.out / 1024).toFixed(1)} KB
        </div>
        <div className="p-2 bg-gray-100 rounded">
          <p className="font-medium">In</p>
          {(stats.in / 1024).toFixed(1)} KB
        </div>
      </div>

      <audio ref={audioElm} autoPlay controls className="w-full" />

      <div className="flex justify-center">
        <button
          onClick={toggleMic}
          className={`px-6 py-3 rounded-full text-white font-bold ${
            micOn ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'
          }`}
        >
          {micOn ? 'Stop' : 'Start'} Speaking
        </button>
      </div>

      {talk && (
        <div className="fixed bottom-4 right-4 bg-green-500 text-white px-4 py-2 rounded-full animate-pulse">
          Speaking…
        </div>
      )}
    </div>
  )
}