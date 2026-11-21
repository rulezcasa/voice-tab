import { useState } from 'react'
import * as api from '../lib/api'

const REASON: Record<string, string> = {
  'over budget': 'over your budget',
  'outside radius': 'farther than you’ll go',
  'too long a trip': 'too long a trip for you',
}
const HINTS = [
  { h: 'cheaper', label: 'Somewhere cheaper' },
  { h: 'closer', label: 'Somewhere closer' },
  { h: 'different_kind', label: 'Something different' },
  { h: 'none', label: 'No preference' },
]

/**
 * It's your turn in a live plan: your agent has drafted an answer from your private details. Send it as is,
 * change it, or say you can't come. The private reason is shown only here, to you.
 */
export function YourTurn({ plan, token, onDone }: { plan: api.MyLivePlan; token: string; onDone: (p: api.MyLivePlan) => void }) {
  const turn = plan.your_turn!
  const [mode, setMode] = useState<'draft' | 'accept' | 'decline'>('draft')
  const [message, setMessage] = useState('')
  const [hint, setHint] = useState(turn.draft.hint !== 'none' ? turn.draft.hint : 'cheaper')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const answer = async (action: api.LiveAction) => {
    setBusy(true)
    setError('')
    try {
      onDone(await api.respondLive(token, plan.id, action, message.trim(), action === 'decline' ? hint : undefined))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const f = turn.facts
  const flip = turn.draft.decision === 'accept' ? 'decline' : 'accept'

  return (
    <div className="your-turn" role="region" aria-label="Your turn">
      <p className="yt-title">
        Your turn · round {plan.rounds} · {plan.proposal?.venue}
        {plan.seconds_left != null && <span> · {plan.seconds_left}s left, then your agent answers</span>}
      </p>
      <div className={`msg agent mine ${turn.draft.decision}`}>
        <span className="who">Your agent’s draft</span>
        <span className="text">{turn.draft.message}</span>
        <span className="msg-tag">{turn.draft.decision === 'accept' ? 'in' : 'out'}</span>
        <span className="private">
          Only you see this: {f.ok ? 'it fits your limits' : `it’s ${REASON[f.reason ?? ''] ?? f.reason}`} (about ${f.total} for
          you, {f.travel_min} min away).
        </span>
      </div>

      {mode === 'draft' ? (
        <div className="ap-row">
          <button className="create" disabled={busy} onClick={() => answer('approve')}>Send it</button>
          <button className="chip" disabled={busy} onClick={() => setMode(flip)}>
            {flip === 'accept' ? 'Actually, I’m in' : 'Actually, no'}
          </button>
          <button className="chip" disabled={busy} onClick={() => answer('leave')}>I can’t come</button>
        </div>
      ) : (
        <div className="yt-edit">
          <input
            className="hg-note"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={mode === 'accept' ? 'Say something (optional)' : 'Why not? (optional, the group sees this)'}
            maxLength={200}
            aria-label="Your message"
          />
          {mode === 'decline' && (
            <div className="chips" role="radiogroup" aria-label="What would work better">
              {HINTS.map(({ h, label }) => (
                <button key={h} role="radio" aria-checked={hint === h} className={`chip ${hint === h ? 'on' : ''}`} onClick={() => setHint(h)}>
                  {label}
                </button>
              ))}
            </div>
          )}
          {mode === 'accept' && !f.ok && <p className="hg-hint warn">This is {REASON[f.reason ?? ''] ?? f.reason}. Your call.</p>}
          <div className="ap-row">
            <button className="create" disabled={busy} onClick={() => answer(mode)}>
              {mode === 'accept' ? 'Send: I’m in' : 'Send: not this one'}
            </button>
            <button className="chip" disabled={busy} onClick={() => setMode('draft')}>Back</button>
          </div>
        </div>
      )}
      {error && <p className="form-error">{error}</p>}
    </div>
  )
}
