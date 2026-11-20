import { useMemo } from 'react'

const COLORS = ['#ff6a2b', '#3d7bff', '#10a87a', '#e0a400', '#ec3f86', '#9a4dff']

/** A one-off burst of confetti over the screen. Pure CSS, no library; skipped for reduced motion. */
export function Confetti({ pieces = 90 }: { pieces?: number }) {
  const bits = useMemo(
    () =>
      Array.from({ length: pieces }, (_, i) => ({
        left: Math.random() * 100,
        delay: Math.random() * 0.6,
        dur: 2.2 + Math.random() * 1.6,
        drift: (Math.random() - 0.5) * 160,
        spin: (Math.random() - 0.5) * 900,
        w: 6 + Math.random() * 6,
        h: 8 + Math.random() * 8,
        color: COLORS[i % COLORS.length],
        round: Math.random() < 0.3,
      })),
    [pieces],
  )
  return (
    <div className="confetti" aria-hidden="true">
      {bits.map((b, i) => (
        <i
          key={i}
          style={
            {
              left: `${b.left}%`,
              width: b.w,
              height: b.round ? b.w : b.h,
              background: b.color,
              borderRadius: b.round ? '50%' : 2,
              animationDelay: `${b.delay}s`,
              animationDuration: `${b.dur}s`,
              '--drift': `${b.drift}px`,
              '--spin': `${b.spin}deg`,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  )
}
