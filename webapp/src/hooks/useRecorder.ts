import { useCallback, useEffect, useRef } from 'react'

const SPEAKING = 0.12 // level that counts as talking
const QUIET = 0.06 // level that counts as silence
const END_SILENCE_MS = 1300 // this much quiet after talking ends the recording
const NO_SPEECH_MS = 6000 // give up if nothing is said
const MAX_MS = 15000

const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']

/**
 * Records the mic and writes its loudness (0..1) into a ref for the orb. Stops by itself
 * when you go quiet (calls onAutoStop), or when stop() is called; both resolve the audio.
 * Needs HTTPS (or localhost). Without a mic, level is faked and the audio is null.
 */
export function useRecorder(onAutoStop: (audio: Blob | null) => void) {
  const levelRef = useRef(0)
  const stopRef = useRef<() => Promise<Blob | null>>(async () => null)
  const onAutoStopRef = useRef(onAutoStop)
  useEffect(() => {
    onAutoStopRef.current = onAutoStop
  }, [onAutoStop])

  const start = useCallback(async () => {
    await stopRef.current()
    let raf = 0
    let stream: MediaStream | null = null
    let ctx: AudioContext | null = null
    let recorder: MediaRecorder | null = null
    let stopped = false
    const chunks: Blob[] = []
    let done: Promise<Blob | null> = Promise.resolve(null)

    const cleanup = () => {
      cancelAnimationFrame(raf)
      stream?.getTracks().forEach((t) => t.stop())
      ctx?.close().catch(() => {})
      levelRef.current = 0
    }

    stopRef.current = async () => {
      if (stopped) return done
      stopped = true
      if (recorder && recorder.state !== 'inactive') recorder.stop()
      else cleanup()
      return done
    }

    const fake = () => {
      const t = performance.now() / 1000
      levelRef.current = 0.18 + 0.22 * Math.abs(Math.sin(t * 3.1) * Math.sin(t * 1.7))
      raf = requestAnimationFrame(fake)
    }

    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      ctx = new AC() // created inside the tap so iOS lets it run
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('no mic api')
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      if (stopped) return cleanup()
      await ctx.resume()

      const mimeType = MIME_TYPES.find((m) => MediaRecorder.isTypeSupported(m))
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      done = new Promise((resolve) => {
        recorder!.onstop = () => {
          cleanup()
          resolve(chunks.length ? new Blob(chunks, { type: recorder!.mimeType || mimeType || 'audio/webm' }) : null)
        }
      })
      recorder.start()

      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Float32Array(analyser.fftSize)
      const began = performance.now()
      let talked = false
      let quietSince = 0

      const loop = () => {
        if (stopped) return // a tap already stopped it; don't send twice
        analyser.getFloatTimeDomainData(buf)
        let sum = 0
        for (const v of buf) sum += v * v
        const level = Math.min(1, Math.sqrt(sum / buf.length) * 7)
        levelRef.current = level

        const now = performance.now()
        if (level > SPEAKING) {
          talked = true
          quietSince = 0
        } else if (level < QUIET && talked) {
          quietSince ||= now
        }
        const end =
          (talked && quietSince && now - quietSince > END_SILENCE_MS) ||
          (!talked && now - began > NO_SPEECH_MS) ||
          now - began > MAX_MS
        if (end) {
          stopRef.current().then((audio) => onAutoStopRef.current(audio))
          return
        }
        raf = requestAnimationFrame(loop)
      }
      loop()
    } catch {
      if (!stopped) fake()
    }
  }, [])

  const stop = useCallback(() => stopRef.current(), [])

  return { levelRef, start, stop }
}
