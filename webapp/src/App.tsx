import { useCallback, useEffect, useRef, useState } from 'react'
import { Hangout } from './components/Hangout'
import { Ledger } from './components/Ledger'
import { MapView } from './components/MapView'
import { Orb } from './components/Orb'
import { ReceiptCard } from './components/ReceiptCard'
import { Progress } from './components/Trail'
import { useHangout } from './hooks/useHangout'
import { useRecorder } from './hooks/useRecorder'
import * as api from './lib/api'
import type { Activity, OrbState, Person, Receipt } from './lib/types'

function greeting(name: string) {
  const h = new Date().getHours()
  const part = h < 5 ? 'Late night' : h < 12 ? 'Morning' : h < 17 ? 'Afternoon' : 'Evening'
  return `${part}, ${name}. What did you spend?`
}

export default function App() {
  const [orb, setOrb] = useState<OrbState>('idle')
  const [people, setPeople] = useState<Person[]>([])
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState<Activity[]>([])
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [hangoutOpen, setHangoutOpen] = useState(false)
  const [cardOpen, setCardOpen] = useState(false) // voice card pinned open (to type), even while idle
  const hangout = useHangout()

  const session = useRef(crypto.randomUUID()) // one conversation per page load, so follow-up answers land
  const timers = useRef<number[]>([])
  const later = (fn: () => void, ms: number) => timers.current.push(window.setTimeout(fn, ms))
  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  // Real people, balances and recent expenses from the backend.
  useEffect(() => {
    api.balances().then(setPeople).catch(() => {})
    api.history().then(setHistory).catch(() => {})
  }, [])

  const me = people.find((p) => p.is_me)

  const say = (text: string) => {
    const words = text.split(' ')
    words.forEach((_, i) => later(() => setReply(words.slice(0, i + 1).join(' ')), i * 45))
  }

  /** Sends audio or text to the agent, then shows the reply and moves balances. Its steps stay behind the scenes. */
  const send = useCallback(async (input: { audio: Blob } | { text: string }, shown: string) => {
    clearTimers()
    setHeard(shown)
    setReply('')
    setReceipt(null)
    setRunning(true)
    setOrb('thinking')

    let r: api.IngestResult
    try {
      r = await api.ingest(input, session.current)
    } catch (e) {
      setRunning(false)
      setOrb('reply')
      say(`Something went wrong: ${(e as Error).message}`)
      return
    }

    setHeard(r.transcript)
    setRunning(false)
    setOrb(r.asking ? 'ask' : 'reply')
    say(r.reply)
    setPeople(r.people)
    if (r.receipt) {
      setReceipt(r.receipt)
      setHistory((h) => [...h, { heard: r.transcript, steps: r.steps, receipt: r.receipt! }])
    }
    if (!r.asking) later(() => setOrb((o) => (o === 'reply' ? 'idle' : o)), 9000)
  }, [])

  const onAudio = useCallback(
    (audio: Blob | null) => {
      if (audio) return send({ audio }, '')
      setOrb('reply')
      setReply('I couldn’t use the microphone here. Try typing instead.')
    },
    [send],
  )

  const mic = useRecorder(onAudio) // stops by itself when you go quiet

  const onTap = useCallback(async () => {
    if (running) return
    setCardOpen(true)
    if (orb === 'listening') return onAudio(await mic.stop())
    clearTimers()
    setHeard('')
    setReply('')
    setReceipt(null)
    setOrb('listening')
    mic.start()
  }, [orb, running, mic, onAudio])

  // Space bar talks on desktop (unless you're typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || sheetOpen || hangout.placing !== null) return
      if ((e.target as HTMLElement).closest('input, textarea, button')) return
      e.preventDefault()
      onTap()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onTap, sheetOpen, hangout.placing])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = typed.trim()
    if (!text || running) return
    setTyped('')
    ;(document.activeElement as HTMLElement | null)?.blur()
    send({ text }, text)
  }

  const shownReply = reply || (orb === 'idle' && !heard ? greeting(me?.name ?? 'there') : '')
  const showCard = cardOpen || running || orb !== 'idle' || !!receipt

  /** Put the voice away: the orb stays, ambient, in its corner. */
  const dismiss = () => {
    if (running) return
    if (orb === 'listening') mic.stop()
    clearTimers()
    setOrb('idle')
    setHeard('')
    setReply('')
    setReceipt(null)
    setCardOpen(false)
  }

  return (
    <div className={`app ${hangoutOpen ? 'hg-open' : ''}`} data-state={orb}>
      <MapView hangout={hangout} panelOpen={hangoutOpen} />
      <div className="aura" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <header className="top">
        <div className="top-l">
          <span className="mark">Keep Tab</span>
          <button className={`pill ${hangoutOpen ? 'on' : ''}`} onClick={() => setHangoutOpen((o) => !o)} aria-expanded={hangoutOpen}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="8" cy="9" r="3" />
              <circle cx="16" cy="9" r="3" />
              <path d="M3 19c.6-3 2.6-4.5 5-4.5s4.4 1.5 5 4.5M11 19c.6-3 2.6-4.5 5-4.5s4.4 1.5 5 4.5" />
            </svg>
            Hangout
          </button>
        </div>
        <button className="icon-btn" onClick={() => setSheetOpen(true)} aria-label="Open ledger">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 7h14M5 12h14M5 17h9" />
          </svg>
        </button>
      </header>

      <Hangout open={hangoutOpen} onClose={() => setHangoutOpen(false)} hangout={hangout} />

      <div className={`voice-dock ${showCard ? 'open' : ''}`}>
        <section className="voice-card" aria-live="polite" aria-hidden={!showCard}>
          <button className="vc-close" onClick={dismiss} disabled={running} aria-label="Put Tab away">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
          <p className={`heard ${orb === 'listening' ? 'live' : ''}`}>
            {orb === 'listening' ? 'listening' : heard ? `“${heard}”` : ''}
          </p>
          <p className="reply" key={shownReply ? 'r' : 'e'}>
            {shownReply}
          </p>
          {receipt && !running ? <ReceiptCard receipt={receipt} /> : <Progress steps={[]} running={running} />}
          <form className="type" onSubmit={onSubmit} autoComplete="off">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={orb === 'ask' ? 'or type your answer…' : 'or type it…'}
              enterKeyHint="send"
              aria-label="Type an expense or a question"
              tabIndex={showCard ? 0 : -1}
            />
            <button type="submit" aria-label="Send" disabled={!typed.trim() || running} tabIndex={showCard ? 0 : -1}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 19V5M6 11l6-6 6 6" />
              </svg>
            </button>
          </form>
        </section>

        <div className="orb-float">
          <Orb state={orb} levelRef={mic.levelRef} onTap={onTap} label={orb === 'listening' ? 'Stop listening' : 'Tap to talk'} />
          {!showCard && (
            <button className="kb-btn" onClick={() => setCardOpen(true)} aria-label="Type to Tab">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="3" y="6" width="18" height="12" rx="2" />
                <path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <Ledger open={sheetOpen} onClose={() => setSheetOpen(false)} people={people} history={history} />
    </div>
  )
}
