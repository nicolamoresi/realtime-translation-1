'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { createWebSocket, WSMessage } from '@/utils/websocket'

export default function RoomPage() {
  const { roomId } = useParams()
  const router = useRouter()
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null
  const [transcripts, setTranscripts] = useState<string[]>([])
  const [micEnabled, setMicEnabled] = useState(false)

  const audioWs = useRef<WebSocket | null>(null)
  const videoWs = useRef<WebSocket | null>(null)
  const localVideoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)
  const remoteAudioRef = useRef<HTMLAudioElement>(null)
  const recorderRef = useRef<MediaRecorder| null>(null)
  const sendFrameInterval = useRef<number | null>(null)

  // 1) On mount: set up video, sockets, but do NOT request audio yet
  useEffect(() => {
    if (!token) {
      router.push('/signin')
      return
    }

    // setup audio WS (will only be used once micEnabled)
    audioWs.current = createWebSocket(
      `/ws/voice/${roomId}`,
      token,
      (msg: WSMessage) => {
        if (msg.transcript) {
          setTranscripts(t => [...t, msg.transcript!, `(en) ${msg.translated}`])
        }
      },
      (data: ArrayBuffer) => {
        if (remoteAudioRef.current) {
          const blob = new Blob([data], { type: 'audio/webm' })
          const url = URL.createObjectURL(blob)
          remoteAudioRef.current.src = url
          remoteAudioRef.current.play().catch(() => {})
          setTimeout(() => URL.revokeObjectURL(url), 30_000)
        }
      }
    )

    // setup video WS
    videoWs.current = createWebSocket(
      `/ws/video/${roomId}`,
      token,
      msg => {
        if (msg.video && remoteVideoRef.current) {
          remoteVideoRef.current.src = `data:video/webm;base64,${msg.video}`
        }
      }
    )

    // immediately request camera only
    navigator.mediaDevices.getUserMedia({ video: true })
      .then(stream => {
        if (localVideoRef.current) {
          localVideoRef.current.srcObject = stream
        }
        // capture video frames
        const canvas = document.createElement('canvas')
        const ctx = canvas.getContext('2d')!
        canvas.width = 320
        canvas.height = 240
        const sendFrame = () => {
          const ws = videoWs.current
          if (ws?.readyState !== WebSocket.OPEN) return
          const video = localVideoRef.current
          if (!video) return
          ctx.drawImage(video, 0, 0, 320, 240)
          canvas.toBlob(blob => {
            if (!blob) return
            const reader = new FileReader()
            reader.onload = () => {
              const b64 = (reader.result as string).split(',')[1]
              ws.send(b64)
            }
            reader.readAsDataURL(blob)
          }, 'video/webm')
        }
        videoWs.current?.addEventListener('open', () => {
          sendFrameInterval.current = window.setInterval(sendFrame, 200)
        })
      })
      .catch(err => console.error('Camera access error:', err))

    return () => {
      // cleanup on unmount
      if (sendFrameInterval.current) clearInterval(sendFrameInterval.current)
      recorderRef.current?.stop()
      audioWs.current?.close()
      videoWs.current?.close()
    }
  }, [roomId, token, router])

  // 2) When user clicks "Enable Microphone", ask for audio permission & start streaming
  const enableMic = () => {
    if (micEnabled) return
    setMicEnabled(true)
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        // start recording
        const recorder = new MediaRecorder(stream)
        recorder.ondataavailable = async e => {
          const ws = audioWs.current
          if (ws?.readyState === WebSocket.OPEN) {
            const buffer = await e.data.arrayBuffer()
            ws.send(buffer)
          }
        }
        recorder.start(250)  // smaller chunks (<500ms) for lower latency
        recorderRef.current = recorder
      })
      .catch(err => {
        console.error('Microphone access error:', err)
        setMicEnabled(false)
      })
  }

  return (
    <div className="p-4 grid grid-cols-2 gap-4">
      <div>
        <h2 className="font-bold mb-2">Local Video</h2>
        <video ref={localVideoRef} autoPlay muted className="w-full rounded" />
        <button
          onClick={enableMic}
          disabled={micEnabled}
          className="mt-2 px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50"
        >
          {micEnabled ? 'Microphone Enabled' : 'Enable Microphone'}
        </button>
      </div>
      <div>
        <h2 className="font-bold mb-2">Remote Video</h2>
        <video ref={remoteVideoRef} autoPlay className="w-full rounded" />
      </div>
      <div className="col-span-2 space-y-4">
        <div>
          <h2 className="font-bold mb-2">Remote Audio</h2>
          <audio ref={remoteAudioRef} controls className="w-full" />
        </div>
        <div>
          <h2 className="font-bold mb-2">Transcripts</h2>
          <div className="h-40 overflow-y-auto bg-gray-100 p-2 rounded">
            {transcripts.map((t, i) => (
              <p key={i} className="text-sm">{t}</p>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
