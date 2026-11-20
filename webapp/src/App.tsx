import { useCallback, useEffect, useRef, useState } from 'react'
import { Ledger } from './components/Ledger'
import { Orb } from './components/Orb'
import { People } from './components/People'
import { ReceiptCard } from './components/ReceiptCard'
import { Progress } from './components/Trail'
import { useMicLevel } from './hooks/useMicLevel'
import { cents, fromCents, isoDay } from './lib/format'
import { DEMO_RUN, HISTORY, PEOPLE } from './lib/sample'
import type { Activity, OrbState, Person, Receipt, TrailStep } from './lib/types'

function greeting(name: string) {
  const h = new Date().getHours()
  const part = h < 5 ? 'Late night' : h < 12 ? 'Morning' : h < 17 ? 'Afternoon' : 'Evening'
  return `${part}, ${name}. What did you spend?`
}

export default function App() {
  const [orb, setOrb] = useState<OrbState>('idle')
  const [people, setPeople] = useState<Person[]>(PEOPLE)
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const [steps, setSteps] = useState<TrailStep[]>([])
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState<Activity[]>(HISTORY)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [splitWith, setSplitWith] = useState<string[]>([]) // who orbits the light after a split

  const mic = useMicLevel()
  const timers = useRef<number[]>([])
  const later = (fn: () => void, ms: number) => timers.current.push(window.setTimeout(fn, ms))
  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  const me = people.find((p) => p.is_me)

  /** Plays the canned pipeline run: steps tick in, then the reply, then balances move. */
  const play = useCallback(
    (said: string, viaVoice: boolean) => {
      clearTimers()
      mic.stop()
      setHeard(said)
      setReply('')
      setSteps([])
      setReceipt(null)
      setRunning(true)
      setOrb('thinking')

      const run = DEMO_RUN.steps.filter((s) => viaVoice || s.step !== 'transcribe')
      let t = 250
      run.forEach((s) => {
        t += Math.max(170, s.ms * 0.9)
        later(() => setSteps((cur) => [...cur, s]), t)
      })

      later(() => {
        setRunning(false)
        setOrb('reply')
        const words = DEMO_RUN.reply.split(' ')
        words.forEach((_, i) => later(() => setReply(words.slice(0, i + 1).join(' ')), i * 45))
        setSplitWith(Object.keys(DEMO_RUN.deltas))
        setPeople((ps) =>
          ps.map((p) => {
            const d = DEMO_RUN.deltas[p.name]
            return d ? { ...p, net: fromCents(cents(p.net) + cents(d)) } : p
          }),
        )
        const r: Receipt = { ...DEMO_RUN.receipt, spent_on: isoDay(new Date()), logged_at: new Date().toISOString() }
        setReceipt(r)
        setHistory((h) => [...h, { heard: said, steps: run, receipt: r }])
        later(() => setOrb((o) => (o === 'reply' ? 'idle' : o)), 9000)
      }, t + 350)
    },
    [mic],
  )

  const onTap = useCallback(() => {
    if (running) return
    if (orb === 'listening') return play(DEMO_RUN.heard, true)
    clearTimers()
    setHeard('')
    setReply('')
    setSteps([])
    setReceipt(null)
    setOrb('listening')
    mic.start()
    later(() => play(DEMO_RUN.heard, true), 4200) // auto-stop, like silence detection will
  }, [orb, running, mic, play])

  // Space bar talks on desktop (unless you're typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || sheetOpen) return
      if ((e.target as HTMLElement).closest('input, textarea, button')) return
      e.preventDefault()
      onTap()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onTap, sheetOpen])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = typed.trim()
    if (!text || running) return
    setTyped('')
    ;(document.activeElement as HTMLElement | null)?.blur()
    play(text, false)
  }

  const shownReply = reply || (orb === 'idle' && !heard ? greeting(me?.name ?? 'there') : '')

  return (
    <div className={`app ${receipt ? 'has-card' : ''}`} data-state={orb}>
      <div className="aura" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <header className="top">
        <div className="brand">
          <span className="mark">Tab</span>
        </div>
        <button className="icon-btn" onClick={() => setSheetOpen(true)} aria-label="Open ledger">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 7h14M5 12h14M5 17h9" />
          </svg>
        </button>
      </header>

      <main className="stage">
        <div className="orb-wrap">
          <Orb state={orb} levelRef={mic.levelRef} onTap={onTap} label={orb === 'listening' ? 'Stop listening' : 'Tap to talk'} />
          <People people={people} show={splitWith} visible={orb === 'reply' || orb === 'ask'} />
        </div>

        <section className="voice" aria-live="polite">
          <p className={`heard ${orb === 'listening' ? 'live' : ''}`}>
            {orb === 'listening' ? 'listening' : heard ? `“${heard}”` : ''}
          </p>
          <p className="reply" key={shownReply ? 'r' : 'e'}>
            {shownReply}
          </p>
        </section>

        {receipt && !running ? <ReceiptCard receipt={receipt} /> : <Progress steps={steps} running={running} />}
      </main>

      <footer className="dock">
        <form className="type" onSubmit={onSubmit} autoComplete="off">
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="or type it…"
            enterKeyHint="send"
            aria-label="Type an expense or a question"
          />
          <button type="submit" aria-label="Send" disabled={!typed.trim() || running}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 19V5M6 11l6-6 6 6" />
            </svg>
          </button>
        </form>
      </footer>

      <Ledger open={sheetOpen} onClose={() => setSheetOpen(false)} people={people} history={history} />
    </div>
  )
}
