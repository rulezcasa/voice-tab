import { useCallback, useEffect, useState } from 'react'
import * as api from '../lib/api'
import { YourTurn } from './YourTurn'

const MODES = ['walk', 'bike', 'transit', 'drive'] as const
const MINUTES = [10, 15, 20, 30, 40, 45, 60]

const day = (iso: string) => new Date(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
const hm = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
const REASON: Record<string, string> = {
  'over budget': 'over your budget',
  'outside radius': 'outside how far you’ll go',
  'too long a trip': 'too long a trip for you',
}

/**
 * Your own agent, on your own device (opened from your private link). You set what it knows about you, which
 * only it ever sees, and you can read what it said for you and why. Nobody else can open this page.
 */
export function AgentPage({ token }: { token: string }) {
  const [me, setMe] = useState<api.MyAgent | null>(null)
  const [activity, setActivity] = useState<api.MyNegotiation[]>([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [form, setForm] = useState({ budget: '', radius: '', minutes: 30, mode: 'transit' as api.MyProfile['travel_mode'], interests: '' })
  const [slot, setSlot] = useState({ date: '', from: '18:00', to: '21:00', label: '' })
  const [livePlans, setLivePlans] = useState<api.MyLivePlan[]>([])

  // live plans: check every few seconds so a new proposal shows up without refreshing
  useEffect(() => {
    let stop = false
    const poll = async () => {
      try {
        const plans = await api.myLive(token)
        if (!stop) setLivePlans(plans)
      } catch {
        /* try again next time */
      }
    }
    poll()
    const t = window.setInterval(poll, 3000)
    return () => {
      stop = true
      window.clearInterval(t)
    }
  }, [token])
  const open = livePlans.filter((p) => p.status === 'waiting')

  const load = useCallback(async () => {
    try {
      const m = await api.myAgent(token)
      setMe(m)
      setForm({
        budget: m.profile.budget ? String(Number(m.profile.budget)) : '',
        radius: m.profile.radius_mi != null ? String(m.profile.radius_mi) : '',
        minutes: m.profile.max_travel_min ?? 30,
        mode: m.profile.travel_mode ?? 'transit',
        interests: m.profile.interests.join(', '),
      })
      setActivity(await api.myAgentActivity(token))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [token])
  useEffect(() => {
    load()
  }, [load])

  const flash = (msg: string) => {
    setSaved(msg)
    window.setTimeout(() => setSaved(''), 2200)
  }

  const save = async () => {
    setError('')
    try {
      setMe(
        await api.updateMyProfile(token, {
          budget: form.budget || undefined,
          radius_mi: form.radius ? Number(form.radius) : undefined,
          max_travel_min: form.minutes,
          travel_mode: form.mode ?? undefined,
          interests: form.interests.split(',').map((s) => s.trim()).filter(Boolean),
        }),
      )
      flash('Saved. Only your agent can see this.')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const useLocation = () => {
    if (!navigator.geolocation) return setError('This browser can’t share a location.')
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          setMe(await api.updateMyProfile(token, { home: [pos.coords.longitude, pos.coords.latitude] }))
          flash('Home updated. Only your agent knows it.')
        } catch (e) {
          setError((e as Error).message)
        }
      },
      () => setError('Couldn’t get your location.'),
      { enableHighAccuracy: false, timeout: 8000 },
    )
  }

  const addBusy = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!slot.date) return setError('Pick a day.')
    try {
      setMe(await api.addMyBusy(token, `${slot.date}T${slot.from}`, `${slot.date}T${slot.to}`, slot.label))
      setSlot((s) => ({ ...s, label: '' }))
      flash('Added. Your agent will keep that time free of plans.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (error && !me) {
    return (
      <main className="agent-page">
        <h1>Your agent</h1>
        <p className="form-error">{error}</p>
      </main>
    )
  }
  if (!me) return <main className="agent-page"><p className="ap-muted">Opening your agent…</p></main>

  return (
    <main className="agent-page">
      <header className="ap-head">
        <span className="mark">Keep Tab</span>
        <h1>{me.person.name.split(' ')[0]}’s agent</h1>
        <p className="ap-muted">
          This page is only for you. What you set here stays with your agent: when your groups plan something, it
          answers for you with a yes or no and a hint, and never shares your budget, home or calendar.
        </p>
        {me.groups.length > 0 && <p className="ap-muted">Your groups: {me.groups.join(', ')}</p>}
      </header>

      {open.length > 0 && (
        <section className="ap-card ap-live">
          <h2>Needs your answer</h2>
          {open.map((p) =>
            p.your_turn ? (
              <div key={`${p.id}-${p.rounds}`}>
                <p className="ap-muted">{p.group.name}: the coordinator proposed {p.proposal?.venue}.</p>
                <YourTurn plan={p} token={token} onDone={(np) => setLivePlans((ps) => ps.map((x) => (x.id === np.id ? np : x)))} />
              </div>
            ) : (
              <p key={p.id} className="ap-muted">
                {p.group.name}: {p.you_left ? 'you left this plan.' : p.you_answered ? `you’ve answered; waiting on ${p.waiting_on.join(', ') || 'the next round'}.` : 'waiting…'}
              </p>
            ),
          )}
        </section>
      )}

      <section className="ap-card">
        <h2>What your agent knows</h2>
        <label>
          <span>Most you’ll spend on a hangout</span>
          <div className="ap-money">
            $<input inputMode="decimal" value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value })} aria-label="Budget in dollars" />
          </div>
        </label>
        <label>
          <span>How far from home you’ll go (miles)</span>
          <input inputMode="decimal" value={form.radius} onChange={(e) => setForm({ ...form, radius: e.target.value })} aria-label="Radius in miles" />
        </label>
        <label>
          <span>Longest trip each way</span>
          <select value={form.minutes} onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })} aria-label="Longest trip">
            {MINUTES.map((m) => (
              <option key={m} value={m}>{m} min</option>
            ))}
          </select>
        </label>
        <div className="ap-row" role="radiogroup" aria-label="How you get around">
          {MODES.map((m) => (
            <button key={m} role="radio" aria-checked={form.mode === m} className={`chip ${form.mode === m ? 'on' : ''}`} onClick={() => setForm({ ...form, mode: m })}>
              {m}
            </button>
          ))}
        </div>
        <label>
          <span>Things you like (comma-separated)</span>
          <input value={form.interests} onChange={(e) => setForm({ ...form, interests: e.target.value })} placeholder="ramen, bowling, cafe" aria-label="Interests" />
        </label>
        <div className="ap-row">
          <button className="create" onClick={save}>Save</button>
          <button className="chip" onClick={useLocation}>{me.profile.home ? 'Update home to where I am' : 'Set home to where I am'}</button>
        </div>
        <p className="ap-muted">{me.profile.home ? 'Home is set (only your agent knows where).' : 'No home set yet: your agent can’t judge distances.'}</p>
      </section>

      <section className="ap-card">
        <h2>When you’re busy</h2>
        {me.busy.length === 0 && <p className="ap-muted">Nothing in the next two weeks.</p>}
        <ul className="ap-busy">
          {me.busy.slice(0, 30).map((b) => (
            <li key={b.id}>
              <span>{day(b.starts_at)} · {hm(b.starts_at)}–{hm(b.ends_at)}</span>
              <span className="ap-muted">{b.label}</span>
              <button className="chip" onClick={async () => setMe(await api.removeMyBusy(token, b.id))} aria-label={`Remove ${b.label}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
        <form className="ap-add" onSubmit={addBusy}>
          <input type="date" value={slot.date} onChange={(e) => setSlot({ ...slot, date: e.target.value })} aria-label="Day" />
          <input type="time" value={slot.from} onChange={(e) => setSlot({ ...slot, from: e.target.value })} aria-label="From" />
          <input type="time" value={slot.to} onChange={(e) => setSlot({ ...slot, to: e.target.value })} aria-label="To" />
          <input value={slot.label} onChange={(e) => setSlot({ ...slot, label: e.target.value })} placeholder="What (private)" aria-label="What" />
          <button className="create" type="submit">Add</button>
        </form>
      </section>

      <section className="ap-card">
        <h2>What your agent did for you</h2>
        {activity.length === 0 && <p className="ap-muted">No plans yet. When a group asks the agents, you’ll see the conversation here.</p>}
        {activity.map((n) => (
          <article key={n.id} className="ap-negotiation">
            <p className="ap-muted">
              {n.group.name} · {day(n.at)} · {n.status === 'agreed' && n.agreed ? `agreed on ${n.agreed.venue.name}` : n.reason}
            </p>
            <ol className="chat">
              {n.transcript.map((m, i) => {
                const mine = m.from === n.you
                const why = mine && m.decision ? n.your_agent.find((a) => a.round === m.round && a.venue) : undefined
                return (
                  <li key={i} className={`msg ${m.from === 'coordinator' ? 'coord' : 'agent'} ${mine ? 'mine' : ''} ${m.decision ?? ''}`}>
                    <span className="who">{m.from === 'coordinator' ? 'Coordinator' : mine ? 'Your agent' : `${m.from}'s agent`}</span>
                    <span className="text">{m.text}</span>
                    {why && (
                      <span className="private">
                        Only you see this: {why.ok ? 'it fit your limits' : `it was ${REASON[why.reason ?? ''] ?? why.reason}`}
                        {why.total ? ` (about $${why.total} for you, ${why.travel_min} min away)` : ''}.
                      </span>
                    )}
                  </li>
                )
              })}
            </ol>
          </article>
        ))}
        <button className="chip" onClick={load}>Refresh</button>
      </section>

      {error && <p className="form-error">{error}</p>}
      {saved && <p className="ap-saved" role="status">{saved}</p>}
    </main>
  )
}
