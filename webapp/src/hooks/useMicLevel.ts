import { useCallback, useRef } from 'react'

/**
 * Live microphone loudness (0..1) written into a ref, for the orb to react to.
 * Needs HTTPS (or localhost). If the mic is unavailable it falls back to a gentle
 * fake level so the listening state still feels alive.
 */
export function useMicLevel() {
  const levelRef = useRef(0)
  const stopRef = useRef<() => void>(() => {})

  const start = useCallback(async () => {
    stopRef.current()
    let raf = 0
    let stream: MediaStream | null = null
    let ctx: AudioContext | null = null
    let stopped = false

    const fake = () => {
      const t = performance.now() / 1000
      levelRef.current = 0.18 + 0.22 * Math.abs(Math.sin(t * 3.1) * Math.sin(t * 1.7))
      raf = requestAnimationFrame(fake)
    }

    stopRef.current = () => {
      stopped = true
      cancelAnimationFrame(raf)
      stream?.getTracks().forEach((t) => t.stop())
      ctx?.close().catch(() => {})
      levelRef.current = 0
    }

    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      ctx = new AC() // created inside the tap so iOS lets it run
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('no mic api')
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      if (stopped) return stopRef.current()
      await ctx.resume()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Float32Array(analyser.fftSize)
      const loop = () => {
        analyser.getFloatTimeDomainData(buf)
        let sum = 0
        for (const v of buf) sum += v * v
        levelRef.current = Math.min(1, Math.sqrt(sum / buf.length) * 7)
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
