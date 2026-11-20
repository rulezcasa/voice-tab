import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../lib/api'
import type { HangoutPlace, PlaceKind } from '../lib/types'
import { Confetti } from './Confetti'

const MODES = [
  { id: 'bots', label: 'Play against bots', about: 'You play one person; everyone else is a bot with a random personality, new every game.' },
  { id: 'live', label: 'Ask everyone live', about: 'Each person gets their agent’s draft on their own phone (their private link) to send, change or say they can’t come.' },
  { id: 'instant', label: 'Instant', about: 'Agents answer for everyone straight away from what each person saved. Nobody is asked.' },
] as const
type Mode = (typeof MODES)[number]['id']

const STATUS: Record<string, string> = {
  agreed: 'It’s a plan!',
  no_agreement: 'No agreement this time',
  no_time: 'No time that works for everyone',
  no_venue: 'No place nearby',
  no_people: 'Not enough people',
  waiting: 'The agents are talking',
}

/** Venue kinds from the planner -> the map's place kinds (for its icon). */
const KIND: Record<string, PlaceKind> = {
  cafe: 'cafe', bar: 'bar', ramen: 'restaurant', dining: 'restaurant', steakhouse: 'restaurant',
  bowling: 'activity', escape_room: 'activity', karaoke: 'activity', park: 'activity',
}

export interface Member { id: number; name: string; is_me: boolean }

/** Ask your friends' agents: a coordinator proposes, each person's agent answers (or its person/bot does). */
export function AgentsTalk({ groupId, members, onAgreed, onPeople }: {
  groupId: number
  members: Member[]
  onAgreed?: (place: HangoutPlace) => void
  /** everyone still in the plan, at the rough area their agent shares (for the map) */
  onPeople?: (shared: api.Negotiation['shared']) => void
}) {
  // Playing against bots is the experience for now; live (real phones) and instant stay in the code for later.
  const mode = 'bots' as Mode
  const [draft, setDraft] = useState('') // what you're typing to the group
  const [asked, setAsked] = useState('') // what you sent, shown right away while the agents start
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [plan, setPlan] = useState<api.Negotiation | api.LivePlan | null>(null)
  const [token, setToken] = useState<string | null>(null) // the player's agent link in a game
  const [mine, setMine] = useState<api.MyLivePlan | null>(null)
  const [shown, setShown] = useState(0)
  const end = useRef<HTMLLIElement>(null)
  const announced = useRef<number | string | null>(null)

  const live = plan && 'waiting_on' in plan ? (plan as api.LivePlan) : null
  const waiting = live?.status === 'waiting'
  const isMe = (name: string) => !!live?.players?.[name]?.startsWith('you')

  // instant results appear one message at a time; live plans show messages as they really arrive
  useEffect(() => {
    if (!plan) return
    if (live) return setShown(plan.transcript.length)
    if (shown >= plan.transcript.length) return
    const t = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 150 : 420)
    return () => window.clearTimeout(t)
  }, [plan, live, shown])
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [shown, mine?.your_turn])

  // live plans: keep checking for new answers (bots answer after a few seconds, people whenever they do)
  const refresh = useCallback(async () => {
    if (!live) return
    try {
      setPlan(await api.getLive(live.id))
      if (token) setMine((await api.myLive(token)).find((p) => p.id === live.id) ?? null)
    } catch (e) {
      const msg = (e as Error).message
      if (/no such plan/i.test(msg)) {
        // the server restarted and lost this plan (plans live in memory): end it instead of waiting forever
        setPlan((p) => (p ? { ...p, status: 'no_agreement', reason: 'This plan was lost when the server restarted. Ask again.' } : p))
        setMine(null)
      }
      /* otherwise keep the last state; the next poll will try again */
    }
  }, [live, token])
  useEffect(() => {
    if (!waiting) return
    const t = window.setInterval(refresh, 1500)
    return () => window.clearInterval(t)
  }, [waiting, refresh])

  const done = !!plan && !waiting && shown >= plan.transcript.length

  // put the people on the map (at their shared ~1 km area); updates if someone drops out
  const sharedKey = plan?.shared?.map((s) => s.person_id).join(',') ?? ''
  useEffect(() => {
    if (plan?.shared?.length) onPeople?.(plan.shared)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharedKey, onPeople])

  // the final answer goes on the map, once
  useEffect(() => {
    if (!done || !plan?.agreed) return
    const key = live?.id ?? plan.agreed.starts_at
    if (announced.current === key) return
    announced.current = key
    const v = plan.agreed.venue
    onAgreed?.({
      id: `agreed-${v.id}`, name: v.name, kind: KIND[v.kind] ?? 'activity', location: [v.lng, v.lat],
      address: v.description ?? '', price_level: 2, per_person: '', rating: null, minutes: {},
      why: `Agreed by ${plan.members.join(', ')}`,
    })
  }, [done, plan, live, onAgreed])

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setAsked(text)
    setDraft('')
    setBusy(true)
    setError('')
    setPlan(null)
    setMine(null)
    setShown(0)
    try {
      const me = members.find((m) => m.is_me)?.id ?? null
      const p = await api.askFriends(groupId, text, me)
      setToken(p.player_token ?? null)
      setPlan(p)
      if (p.player_token) setMine((await api.myLive(p.player_token)).find((x) => x.id === p.id) ?? null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const when = plan?.agreed ? new Date(plan.agreed.starts_at) : null

  return (
    <div className="agents">
      {!plan && (
        <section>
          <ol className="chat">
            {!asked && <li className="chat-empty">Ask your friends anything, like “hang out tomorrow?”. Their agents will work it out.</li>}
            {asked && (
              <li className="msg agent mine ask">
                <span className="who">You</span>
                <span className="text">{asked}</span>
              </li>
            )}
            {busy && <li className="typing" aria-label="The agents are thinking"><i /><i /><i /></li>}
          </ol>
        </section>
      )}

      {plan && (
        <section>
          {live && mode !== 'instant' && Object.keys(live.players ?? {}).length > 0 && (
            <p className="hg-hint">{Object.entries(live.players).map(([n, role]) => `${n}: ${role}`).join(' · ')}</p>
          )}
          <ol className="chat">
            {plan.transcript.slice(0, shown).map((m, i) => (
              <li key={i} className={`msg ${m.from === 'coordinator' ? 'coord' : 'agent'} ${isMe(m.from) ? 'mine' : ''} ${m.decision ?? ''} ${m.event ?? ''}`}>
                <span className="who">
                  {m.from === 'coordinator' ? 'Coordinator' : isMe(m.from) ? `You (${m.from})` : m.from}
                  {m.round > 0 && <em>round {m.round}</em>}
                </span>
                <span className="text">{m.text}</span>
                {m.decision && (
                  <span className="msg-tag">
                    {m.decision === 'accept' ? 'in' : 'out'}
                    {m.hint && m.hint !== 'none' ? ` · wants ${m.hint.replace('_', ' ')}` : ''}
                    {m.by ? ` · ${m.by}` : ''}
                  </span>
                )}
              </li>
            ))}
            <li ref={end} aria-hidden="true" />
          </ol>

          {waiting && live && (
            <div className="outcome waiting" role="status">
              <b>{STATUS.waiting}</b>
              <span>
                {live.waiting_on.length ? `${live.waiting_on.map((n) => (isMe(n) ? 'your agent' : `${n}’s agent`)).join(', ')} thinking…` : 'Next round…'}
              </span>
            </div>
          )}
          {done && plan.agreed && when && (
            <div className="final" role="status">
              <Confetti />
              <b>{STATUS.agreed}</b>
              <span className="final-place">📍 {plan.agreed.venue.name}</span>
              <span>
                {when.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })} at{' '}
                {when.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })} · {plan.members.join(', ')}
              </span>
              <span className="final-map">Pinned on the map</span>
            </div>
          )}
          {done && !plan.agreed && (
            <div className={`outcome ${plan.status}`} role="status">
              <b>{STATUS[plan.status] ?? plan.status}</b>
              <span>{plan.reason}</span>
            </div>
          )}
        </section>
      )}
      {error && <p className="form-error">{error}</p>}

      {!plan && (
        <form className="hg-foot composer" onSubmit={run}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} disabled={busy} maxLength={280}
            placeholder="Message your friends…" aria-label="Message your friends" enterKeyHint="send" autoFocus />
          <button type="submit" className="create" disabled={busy || !draft.trim()} aria-label="Ask">{busy ? '…' : 'Ask'}</button>
        </form>
      )}
    </div>
  )
}
