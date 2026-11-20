import { useEffect, useRef, useState } from 'react'
import { absMoney, cents, fromCents, initials } from '../lib/format'
import type { Person } from '../lib/types'

/**
 * The people in a split, orbiting the light (you sit at the bottom). Only the names in
 * `show` are drawn, and only while `visible`; balances are tracked for everyone so a
 * change still animates when its node appears.
 */
export function People({ people, show, visible }: { people: Person[]; show: string[]; visible: boolean }) {
  const prev = useRef<Map<number, string>>(new Map())
  const [bumps, setBumps] = useState<Record<number, { delta: string; key: number }>>({})

  useEffect(() => {
    const next: Record<number, { delta: string; key: number }> = {}
    for (const p of people) {
      const before = prev.current.get(p.id)
      if (before !== undefined && before !== p.net) {
        next[p.id] = { delta: fromCents(cents(p.net) - cents(before)), key: Date.now() + p.id }
      }
      prev.current.set(p.id, p.net)
    }
    if (Object.keys(next).length) {
      setBumps((b) => ({ ...b, ...next }))
      const t = setTimeout(() => setBumps({}), 2600)
      return () => clearTimeout(t)
    }
  }, [people])

  const me = people.find((p) => p.is_me)
  const others = people.filter((p) => !p.is_me && show.includes(p.name))
  const slots = others.length + 1 // +1 keeps the bottom slot for you

  if (!others.length) return null

  return (
    <div className={`people ${visible ? 'shown' : ''}`} aria-hidden={!visible}>
      {others.map((p, i) => {
        const angle = 90 + ((i + 1) * 360) / slots // degrees, 90 = bottom
        return <Node key={p.id} p={p} angle={angle} bump={bumps[p.id]} />
      })}
      {me && <Node p={me} angle={90} bump={bumps[me.id]} isMe />}
    </div>
  )
}

function Node({ p, angle, bump, isMe }: { p: Person; angle: number; bump?: { delta: string; key: number }; isMe?: boolean }) {
  const n = Number(p.net)
  const sign = n > 0.004 ? 'pos' : n < -0.004 ? 'neg' : 'zero'
  const rad = (angle * Math.PI) / 180
  const style = {
    '--x': `${(Math.cos(rad) * 41).toFixed(2)}%`,
    '--y': `${(Math.sin(rad) * 43).toFixed(2)}%`,
  } as React.CSSProperties
  const status = isMe
    ? sign === 'neg' ? `you owe ${absMoney(p.net)}` : sign === 'pos' ? `you're owed ${absMoney(p.net)}` : 'all square'
    : sign === 'neg' ? `owes ${absMoney(p.net)}` : sign === 'pos' ? `owed ${absMoney(p.net)}` : 'square'

  return (
    <div className={`node ${sign} ${isMe ? 'me' : ''} ${bump ? 'bumped' : ''}`} style={style}>
      {!isMe && <span className="node-dot">{initials(p.name)}</span>}
      <span className="node-name">{isMe ? 'you' : p.name.split(' ')[0] + (p.name.includes(' ') ? ` ${p.name.split(' ')[1][0]}.` : '')}</span>
      <span className="node-net">{status}</span>
      {bump && (
        <span key={bump.key} className={`node-delta ${Number(bump.delta) < 0 ? 'neg' : 'pos'}`}>
          {Number(bump.delta) > 0 ? '+' : '−'}
          {absMoney(bump.delta)}
        </span>
      )}
    </div>
  )
}
