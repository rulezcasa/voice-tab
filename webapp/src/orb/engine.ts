// Canvas renderer for the orb. Three soft, noise-deformed blobs blended additively,
// with a halo, voice ripples and "thinking" particles. Everything eases toward the
// target for the current state, so state changes morph instead of jumping.
import type { OrbState } from '../lib/types'

type Hues = [number, number, number]

const PALETTE: Record<OrbState, Hues> = {
  idle: [176, 204, 252],
  listening: [12, 34, 346],
  thinking: [266, 226, 298],
  reply: [150, 172, 198],
  ask: [38, 52, 18],
}

interface Feel {
  energy: number // how much the outline wobbles
  scale: number // size relative to base radius
  speed: number // animation speed
  think: number // 0..1 orbiting particles
}

const FEEL: Record<OrbState, Feel> = {
  idle: { energy: 0.05, scale: 1, speed: 0.55, think: 0 },
  listening: { energy: 0.1, scale: 1.05, speed: 1.05, think: 0 },
  thinking: { energy: 0.16, scale: 0.84, speed: 1.9, think: 1 },
  reply: { energy: 0.08, scale: 1.02, speed: 0.75, think: 0 },
  ask: { energy: 0.12, scale: 0.98, speed: 0.9, think: 0 },
}

const TAU = Math.PI * 2
const POINTS = 72
const PARTICLES = 28

function lerpHue(a: number, b: number, k: number) {
  const d = ((b - a + 540) % 360) - 180
  return (a + d * k + 360) % 360
}

export class OrbEngine {
  onHues?: (h: Hues) => void

  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private ro: ResizeObserver
  private w = 0
  private h = 0
  private raf = 0
  private last = 0
  private clock = 0 // real seconds
  private phase = 0 // speed-scaled seconds
  private state: OrbState = 'idle'
  private hues: Hues = [...PALETTE.idle]
  private feel: Feel = { ...FEEL.idle }
  private targetLevel = 0
  private level = 0
  private ripples: { r: number; a: number }[] = []
  private lastRipple = 0
  private reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
    this.ctx = canvas.getContext('2d')!
    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(canvas)
    this.resize()
    this.raf = requestAnimationFrame(this.frame)
  }

  setState(s: OrbState) {
    if (s !== this.state && (s === 'reply' || s === 'ask')) this.pulse()
    this.state = s
  }

  /** 0..1 voice loudness while listening. */
  setLevel(v: number) {
    this.targetLevel = Math.max(0, Math.min(1, v))
  }

  pulse() {
    this.ripples.push({ r: 1, a: 0.5 })
  }

  destroy() {
    cancelAnimationFrame(this.raf)
    this.ro.disconnect()
  }

  private resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const { width, height } = this.canvas.getBoundingClientRect()
    this.w = width
    this.h = height
    this.canvas.width = Math.round(width * dpr)
    this.canvas.height = Math.round(height * dpr)
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  private frame = (ts: number) => {
    const dt = Math.min(0.05, this.last ? (ts - this.last) / 1000 : 0.016)
    this.last = ts
    this.update(dt)
    this.draw()
    this.raf = requestAnimationFrame(this.frame)
  }

  private update(dt: number) {
    const k = 1 - Math.exp(-dt * 3.2)
    const pal = PALETTE[this.state]
    const tgt = FEEL[this.state]
    this.hues = [0, 1, 2].map((i) => lerpHue(this.hues[i], pal[i], k)) as Hues
    for (const key of Object.keys(tgt) as (keyof Feel)[]) {
      this.feel[key] += (tgt[key] - this.feel[key]) * k
    }
    // attack fast, release slow, like a VU meter
    const lk = this.targetLevel > this.level ? 1 - Math.exp(-dt * 18) : 1 - Math.exp(-dt * 4)
    this.level += (this.targetLevel - this.level) * lk

    const motion = this.reduced ? 0.35 : 1
    this.clock += dt
    this.phase += dt * this.feel.speed * motion

    if (this.state === 'listening' && this.level > 0.22 && this.clock - this.lastRipple > 0.32) {
      this.ripples.push({ r: 1, a: 0.25 + this.level * 0.35 })
      this.lastRipple = this.clock
    }
    for (const rp of this.ripples) {
      rp.r += dt * 0.55
      rp.a *= Math.exp(-dt * 1.6)
    }
    this.ripples = this.ripples.filter((rp) => rp.a > 0.01 && rp.r < 1.75)
    this.onHues?.(this.hues)
  }

  private draw() {
    const { ctx, w, h, feel, level, phase } = this
    const cx = w / 2
    const cy = h / 2
    const R = Math.min(w, h) * 0.235 // halo (2R) must stay inside the canvas
    const motion = this.reduced ? 0.6 : 1
    const breathe = 1 + 0.024 * Math.sin(this.clock * 1.25) * motion
    const scale = feel.scale * breathe + level * 0.2
    const amp = (0.03 + feel.energy * 0.35 + level * 0.45) * motion
    const [h0, h1, h2] = this.hues

    ctx.clearRect(0, 0, w, h)
    ctx.globalCompositeOperation = 'lighter'

    // halo
    const halo = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 2.05)
    halo.addColorStop(0, `hsla(${h0}, 90%, 60%, ${0.2 + level * 0.15})`)
    halo.addColorStop(0.5, `hsla(${h1}, 90%, 55%, 0.06)`)
    halo.addColorStop(1, `hsla(${h1}, 90%, 50%, 0)`)
    ctx.fillStyle = halo
    ctx.fillRect(0, 0, w, h)

    // ripples
    for (const rp of this.ripples) {
      ctx.beginPath()
      ctx.arc(cx, cy, R * scale * rp.r, 0, TAU)
      ctx.strokeStyle = `hsla(${h1}, 95%, 70%, ${rp.a})`
      ctx.lineWidth = 1.25
      ctx.stroke()
    }

    // blobs
    const hues = [h0, h1, h2]
    for (let i = 0; i < 3; i++) {
      const ox = Math.cos(phase * 0.6 + i * 2.1) * R * 0.05
      const oy = Math.sin(phase * 0.5 + i * 1.7) * R * 0.05
      const rr = R * scale * (1 - i * 0.07)
      const pts: [number, number][] = []
      for (let j = 0; j < POINTS; j++) {
        const t = (j / POINTS) * TAU
        const n =
          Math.sin(3 * t + phase * 1.3 + i * 2.1) * 0.55 +
          Math.sin(5 * t - phase * 1.7 + i) * 0.3 +
          Math.sin(2 * t + phase * 0.7 + i * 4) * 0.4
        const r = rr * (1 + amp * n)
        pts.push([cx + ox + Math.cos(t) * r, cy + oy + Math.sin(t) * r])
      }
      const g = ctx.createRadialGradient(cx - rr * 0.35, cy - rr * 0.4, 0, cx, cy, rr * 1.25)
      g.addColorStop(0, `hsla(${hues[i]}, 95%, 72%, 0.75)`)
      g.addColorStop(0.55, `hsla(${hues[(i + 1) % 3]}, 90%, 55%, 0.32)`)
      g.addColorStop(1, `hsla(${hues[(i + 2) % 3]}, 90%, 45%, 0)`)
      ctx.fillStyle = g
      ctx.beginPath()
      const mid = (a: [number, number], b: [number, number]) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] as const
      const start = mid(pts[POINTS - 1], pts[0])
      ctx.moveTo(start[0], start[1])
      for (let j = 0; j < POINTS; j++) {
        const p = pts[j]
        const m = mid(p, pts[(j + 1) % POINTS])
        ctx.quadraticCurveTo(p[0], p[1], m[0], m[1])
      }
      ctx.fill()
    }

    // bright core
    const core = ctx.createRadialGradient(cx - R * 0.15, cy - R * 0.2, 0, cx, cy, R * 0.9)
    core.addColorStop(0, `hsla(${h0}, 100%, 92%, ${0.16 + level * 0.22})`)
    core.addColorStop(1, `hsla(${h0}, 100%, 80%, 0)`)
    ctx.fillStyle = core
    ctx.beginPath()
    ctx.arc(cx, cy, R * scale, 0, TAU)
    ctx.fill()

    // thinking particles
    if (feel.think > 0.02) {
      for (let i = 0; i < PARTICLES; i++) {
        const a = (i / PARTICLES) * TAU + this.clock * (0.9 + (i % 3) * 0.25) * motion
        const wob = Math.sin(this.clock * 2 + i * 1.3) * R * 0.08
        const pr = R * (1.32 + (i % 4) * 0.07) + wob
        const size = 1 + (i % 3) * 0.6
        ctx.beginPath()
        ctx.arc(cx + Math.cos(a) * pr, cy + Math.sin(a) * pr, size, 0, TAU)
        ctx.fillStyle = `hsla(${hues[i % 3]}, 95%, 75%, ${feel.think * (0.35 + 0.4 * Math.sin(this.clock * 3 + i) ** 2)})`
        ctx.fill()
      }
    }

    ctx.globalCompositeOperation = 'source-over'
  }
}
