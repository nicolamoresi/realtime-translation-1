export function encodeWav(b64pcm: string, sampleRate = 24000): Uint8Array {
    const pcm = Uint8Array.from(atob(b64pcm), c => c.charCodeAt(0))
    const numSamples = pcm.byteLength / 2
    const header = new ArrayBuffer(44)
    const view = new DataView(header)

    view.setUint32(0, 0x52494646, false)               // 'RIFF'
    view.setUint32(4, 36 + pcm.byteLength, true)
    view.setUint32(8, 0x57415645, false)               // 'WAVE'

    view.setUint32(12, 0x666d7420, false)              // 'fmt '
    view.setUint32(16, 16,               true)         // size
    view.setUint16(20, 1,                true)         // PCM
    view.setUint16(22, 1,                true)         // mono
    view.setUint32(24, sampleRate,       true)
    view.setUint32(28, sampleRate * 2,   true)         // byte rate
    view.setUint16(32, 2,                true)         // block align
    view.setUint16(34, 16,               true)         // bits

    view.setUint32(36, 0x64617461, false)              // 'data'
    view.setUint32(40, pcm.byteLength,   true)

    return new Uint8Array([...new Uint8Array(header), ...pcm])
  }
