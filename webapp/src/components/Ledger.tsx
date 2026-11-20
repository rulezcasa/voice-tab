import { useEffect, useRef, useState } from 'react'
import { absMoney } from '../lib/format'
import type { Activity, Person } from '../lib/types'
import { ReceiptCard } from './ReceiptCard'

type Tab = 'activity' | 'balances'

interface Props {
  open: boolean
  onClose: () => void
  people: Person[]
  history: Activity[]
}

/** Bottom sheet: the ledger behind the voice. Drag the handle down or tap outside to close. */
export function Ledger({ open, onClose, people, history }: Props) {
  const [tab, setTab] = useState<Tab>('activity')
  const [drag, setDrag] = useState(0)
  const start = useRef<number | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const onDown = (e: React.PointerEvent) => {
    start.current = e.clientY
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onMove = (e: React.PointerEvent) => {
    if (start.current !== null) setDrag(Math.max(0, e.clientY - start.current))
  }
  const onUp = () => {
    if (drag > 90) onClose()
    start.current = null
    setDrag(0)
  }

  const maxAbs = Math.max(1, ...people.map((p) => Math.abs(Number(p.net))))

  return (
    <>
      <div className={`scrim ${open ? 'open' : ''}`} onClick={onClose} />
      <aside
        className={`sheet ${open ? 'open' : ''} ${drag ? 'dragging' : ''}`}
        style={drag ? { transform: `translateY(${drag}px)` } : undefined}
        aria-hidden={!open}
        aria-label="Ledger"
      >
        <div className="sheet-handle" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
          <span />
        </div>
        <nav className="tabs" role="tablist">
          {(['activity', 'balances'] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>

        <div className="sheet-body">
          {tab === 'activity' && (
            <div className="history">
              {history.length === 0 && <p className="empty">Nothing yet. Everything you tell Tab shows up here.</p>}
              {[...history].reverse().map((h, i) => (
                <section key={h.receipt.logged_at + i}>
                  <p className="h-heard">“{h.heard}”</p>
                  <ReceiptCard receipt={h.receipt} compact />
                </section>
              ))}
            </div>
          )}

          {tab === 'balances' && (
            <ul className="rows">
              {people.map((p) => {
                const n = Number(p.net)
                return (
                  <li key={p.id} className="row bal">
                    <div className="row-main">
                      <span className="row-title">{p.is_me ? 'You' : p.name}</span>
                      <span className="bar">
                        <i className={n < 0 ? 'neg' : 'pos'} style={{ width: `${(Math.abs(n) / maxAbs) * 50}%` }} />
                      </span>
                    </div>
                    <span className={`row-amt ${n < 0 ? 'neg' : 'pos'}`}>
                      {n < 0 ? 'owes ' : 'owed '}
                      {absMoney(p.net)}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}

        </div>
      </aside>
    </>
  )
}
