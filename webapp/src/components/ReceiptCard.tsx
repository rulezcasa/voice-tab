import { useEffect, useRef, useState } from 'react'
import { initials, money, prettyDay } from '../lib/format'
import type { Receipt, TrailStep } from '../lib/types'
import { HowSteps } from './Trail'

function loggedTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()
}

/** What got logged, in human terms: what, how much, where it's filed, who owes what, when. */
export function ReceiptCard({ receipt: r, steps, compact }: { receipt: Receipt; steps: TrailStep[]; compact?: boolean }) {
  const [showHow, setShowHow] = useState(false)
  const howRef = useRef<HTMLDivElement>(null)
  const split = r.shares.length > 1

  useEffect(() => {
    if (showHow) howRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [showHow])

  return (
    <article className={`receipt ${compact ? 'compact' : ''}`}>
      <header className="rc-head">
        <h3 className="rc-title">{r.description}</h3>
        <span className="rc-amount">{money(r.amount)}</span>
      </header>

      <div className="rc-tags">
        <span className={`tag cat-${r.category}`}>
          <i />
          {r.category}
        </span>
        {r.group && <span className="tag">{r.group}</span>}
        <span className="tag">{prettyDay(r.spent_on)}</span>
      </div>

      {split ? (
        <ul className="rc-shares">
          {r.shares.map((s) => (
            <li key={s.name}>
              <span className={`av ${s.is_me ? 'me' : ''}`}>{s.is_me ? 'you' : initials(s.name)}</span>
              <span className="rc-name">{s.is_me ? 'You' : s.name}</span>
              <span className="rc-what">
                {s.is_me ? (
                  <>
                    paid {money(s.paid)} <em>· your share {money(s.owed)}</em>
                  </>
                ) : (
                  <>owes you {money(s.owed)}</>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rc-solo">Just you. Nothing shared.</p>
      )}

      <footer className="rc-foot">
        <span>Logged {loggedTime(r.logged_at)}</span>
        {steps.length > 0 && (
          <button onClick={() => setShowHow((v) => !v)} aria-expanded={showHow}>
            How Tab did it
            <svg viewBox="0 0 24 24" aria-hidden="true" className={showHow ? 'up' : ''}>
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        )}
      </footer>

      {showHow && (
        <div ref={howRef}>
          <HowSteps steps={steps} />
        </div>
      )}
    </article>
  )
}
