import { initials, money, prettyDay } from '../lib/format'
import type { Receipt } from '../lib/types'

function loggedTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()
}

/** What got logged, in human terms: what, how much, where it's filed, who owes what, when. */
export function ReceiptCard({ receipt: r, compact }: { receipt: Receipt; compact?: boolean }) {
  const split = r.shares.length > 1

  return (
    <article className={`receipt ${compact ? 'compact' : ''}`}>
      <header className="rc-head">
        <h3 className="rc-title">{r.description}</h3>
        <span className="rc-amount">{money(r.amount)}</span>
      </header>

      <div className="rc-tags">
        <span className="tag cat">{r.category}</span>
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
      </footer>
    </article>
  )
}
