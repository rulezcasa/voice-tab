import { useEffect, useRef, useState } from 'react'
import type { Hangout as HangoutState } from '../hooks/useHangout'
import { figureOf, KIND_EMOJI } from '../lib/emoji'
import { AgentsTalk } from './AgentsTalk'
import { money } from '../lib/format'
import type { HangoutMember, PlaceKind, TravelMode } from '../lib/types'

const KINDS: { k: PlaceKind; label: string }[] = [
  { k: 'restaurant', label: 'Food' },
  { k: 'cafe', label: 'Coffee' },
  { k: 'bar', label: 'Drinks' },
  { k: 'retail', label: 'Shopping' },
  { k: 'activity', label: 'Activity' },
]
const MINUTES = [5, 10, 15, 20, 30]
const MODES: { m: TravelMode; label: string }[] = [
  { m: 'walk', label: 'Walk' },
  { m: 'bike', label: 'Bike' },
  { m: 'drive', label: 'Drive' },
]
const PRICE = ['', '$', '$$', '$$$', '$$$$']

interface Props {
  open: boolean
  onClose: () => void
  hangout: HangoutState
}

/** Side panel (bottom sheet on phones): pick a group, set everyone's budget and reach, find places. */
export function Hangout({ open, onClose, hangout: h }: Props) {
  const { loadGroups } = h
  const [mode, setMode] = useState<'plan' | 'agents'>('plan') // plan it here, or let everyone's agents decide
  useEffect(() => {
    if (open) loadGroups()
  }, [open, loadGroups])

  useEffect(() => {
    if (!open || h.placing !== null) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, h.placing])

  // new suggestions: bring them into view
  const results = useRef<HTMLElement>(null)
  useEffect(() => {
    if (h.status === 'done') results.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [h.status, h.result])

  const placingName = h.members.find((m) => m.person_id === h.placing)
  const missing = h.going.filter((m) => !m.location).length

  return (
    <aside className={`hangout ${open ? 'open' : ''} ${h.placing !== null ? 'tucked' : ''}`} aria-hidden={!open} aria-label="Hangout">
      <header className="hg-head">
        <div>
          <h2>Hangout</h2>
          <p>Somewhere that works for everyone.</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close hangout">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </header>

      {placingName && (
        <div className="hg-placing" role="status">
          Tap the map to place <b>{placingName.is_me ? 'yourself' : placingName.name.split(' ')[0]}</b>
          <button onClick={() => h.setPlacing(null)}>Cancel</button>
        </div>
      )}

      <div className="hg-body">
        <section>
          <p className="pick-label">Group</p>
          <div className="chips">
            {h.groups.length === 0 && <span className="hg-hint">No groups yet. Make one from the ledger.</span>}
            {h.groups.map((g) => (
              <button key={g.id} className={`chip ${h.groupId === g.id ? 'on' : ''}`} onClick={() => h.pickGroup(g)}>
                {g.name}
              </button>
            ))}
          </div>
        </section>

        {h.groupId !== null && (
          <section>
            <p className="pick-label">How</p>
            <div className="chips">
              <button className={`chip ${mode === 'plan' ? 'on' : ''}`} onClick={() => { if (mode !== 'plan') h.clearAgentPeople(); setMode('plan') }}>
                Plan it here
              </button>
              <button className={`chip ${mode === 'agents' ? 'on' : ''}`} onClick={() => setMode('agents')}>
                Ask your friends' agents
              </button>
            </div>
          </section>
        )}

        {mode === 'agents' && h.groupId !== null && (
          <AgentsTalk
            groupId={h.groupId}
            members={h.members.map((m) => ({ id: m.person_id, name: m.name, is_me: m.is_me }))}
            onAgreed={h.showAgreed}
            onPeople={h.showAgentPeople}
          />
        )}

        {mode === 'plan' && h.members.length > 0 && (
          <section>
            <p className="pick-label">
              Who's going <span>· {h.going.length} of {h.members.length}</span>
            </p>
            <ul className="hg-people">
              {h.members.map((m) => (
                <MemberRow key={m.person_id} m={m} h={h} />
              ))}
            </ul>
          </section>
        )}

        {mode === 'plan' && h.members.length > 0 && (
          <section>
            <p className="pick-label">Looking for</p>
            <div className="chips">
              {KINDS.map(({ k, label }) => (
                <button key={k} className={`chip ${h.kinds.includes(k) ? 'on' : ''}`} onClick={() => h.toggleKind(k)}>
                  {label}
                </button>
              ))}
            </div>
            <textarea
              className="hg-note"
              rows={2}
              value={h.note}
              onChange={(e) => h.setNote(e.target.value)}
              placeholder="Anything else? Vegetarian, quiet, outdoor seating…"
            />
          </section>
        )}

        {mode === 'plan' && h.status === 'done' && h.result && (
          <section className="hg-results" ref={results}>
            <p className="pick-label">
              Suggestions <span>· {h.result.places.length}</span>
            </p>
            {h.result.places.length === 0 && (
              <p className="hg-hint">Nothing fits everyone's budget and reach. Try a longer trip or a bigger budget.</p>
            )}
            <ol>
              {h.result.places.map((p, i) => (
                <li key={p.id}>
                  <button className={`place ${h.selected === p.id ? 'on' : ''}`} onClick={() => h.setSelected(h.selected === p.id ? null : p.id)}>
                    <span className="place-n" aria-hidden="true">
                      {KIND_EMOJI[p.kind]}
                      <em>{i + 1}</em>
                    </span>
                    <span className="place-main">
                      <span className="place-top">
                        <span className="place-name">{p.name}</span>
                        <span className="place-price">~{money(p.per_person)}</span>
                      </span>
                      <span className="place-sub">
                        {PRICE[p.price_level]} · {p.kind}
                        {p.rating ? ` · ★ ${p.rating}` : ''} · {p.address}
                      </span>
                      <span className="place-why">{p.why}</span>
                      <span className="place-times">
                        {h.going.map((m) => (
                          <span key={m.person_id} style={{ '--c': h.colorOf(m.person_id) } as React.CSSProperties}>
                            <i />
                            {m.is_me ? 'you' : m.name.split(' ')[0]} {p.minutes[m.person_id] ?? '–'}m
                          </span>
                        ))}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        )}
        {mode === 'plan' && h.status === 'error' && <p className="form-error">{h.error}</p>}
      </div>

      {mode === 'plan' && h.members.length > 0 && (
        <footer className="hg-foot">
          {!h.ready ? (
            <p className="hg-hint">
              {h.going.length < 2
                ? 'Pick at least two people.'
                : missing
                  ? `Place ${missing} more ${missing === 1 ? 'person' : 'people'} on the map.`
                  : 'Everyone needs a budget.'}
            </p>
          ) : (
            h.outOfReach.length > 0 && (
              <p className="hg-hint warn">
                {listNames(h.outOfReach)} can't reach the middle in time. Try a longer trip or a faster way there.
              </p>
            )
          )}
          <button className="create" disabled={!h.ready || h.status === 'searching'} onClick={h.search}>
            {h.status === 'searching' ? 'Finding places…' : h.status === 'done' ? 'Search again' : 'Find places'}
          </button>
        </footer>
      )}
    </aside>
  )
}

function listNames(ms: HangoutMember[]) {
  const names = ms.map((m) => (m.is_me ? 'You' : m.name.split(' ')[0]))
  return names.length < 2 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

function MemberRow({ m, h }: { m: HangoutMember; h: HangoutState }) {
  const [locating, setLocating] = useState(false)
  const first = m.is_me ? 'You' : m.name.split(' ')[0]

  const useMine = () => {
    if (!navigator.geolocation) return h.setPlacing(m.person_id)
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        h.place(m.person_id, [pos.coords.longitude, pos.coords.latitude])
      },
      () => {
        setLocating(false)
        h.setPlacing(m.person_id) // denied or unavailable: fall back to tapping the map
      },
      { enableHighAccuracy: true, timeout: 8000 },
    )
  }

  return (
    <li className={`hg-person ${m.going ? '' : 'off'}`} style={{ '--c': h.colorOf(m.person_id) } as React.CSSProperties}>
      <div className="hg-row">
        <button
          className="hg-av"
          onClick={() => h.update(m.person_id, { going: !m.going })}
          aria-pressed={m.going}
          aria-label={`${first} ${m.going ? 'is going' : 'is not going'}`}
        >
          {figureOf(m.person_id, m.is_me)}
        </button>
        <span className="hg-name">{m.is_me ? 'You' : m.name}</span>
        {m.going && (
          <span className="hg-loc">
            {m.is_me && !m.location && (
              <button className="link" onClick={useMine} disabled={locating}>
                {locating ? 'Locating…' : 'Use my location'}
              </button>
            )}
            <button className={`link ${m.location ? 'set' : ''}`} onClick={() => h.setPlacing(m.person_id)}>
              {m.location ? 'Move pin' : 'Set on map'}
            </button>
          </span>
        )}
      </div>

      {m.going && (
        <div className="hg-fields">
          <label className="hg-budget">
            <span>$</span>
            <input
              inputMode="decimal"
              value={m.budget}
              onChange={(e) => h.update(m.person_id, { budget: e.target.value.replace(/[^\d.]/g, '') })}
              aria-label={`${first}'s budget`}
            />
            <em>pp</em>
          </label>
          <select
            value={m.minutes}
            onChange={(e) => h.update(m.person_id, { minutes: Number(e.target.value) })}
            aria-label={`${first}'s travel time`}
          >
            {MINUTES.map((n) => (
              <option key={n} value={n}>
                {n} min
              </option>
            ))}
          </select>
          <div className="seg" role="radiogroup" aria-label={`${first} travels by`}>
            {MODES.map(({ m: mode, label }) => (
              <button
                key={mode}
                role="radio"
                aria-checked={m.mode === mode}
                className={m.mode === mode ? 'on' : ''}
                onClick={() => h.update(m.person_id, { mode })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
    </li>
  )
}
