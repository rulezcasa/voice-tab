import { useCallback, useEffect, useRef, useState } from 'react'
import { Ledger } from './components/Ledger'
import { Orb } from './components/Orb'
import { People } from './components/People'
import { ReceiptCard } from './components/ReceiptCard'
import { Progress } from './components/Trail'
import { useRecorder } from './hooks/useRecorder'
import * as api from './lib/api'
import type { Activity, OrbState, Person, Receipt, TrailStep } from './lib/types'

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
  const [steps, setSteps] = useState<TrailStep[]>([])
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState<Activity[]>([])
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [splitWith, setSplitWith] = useState<string[]>([]) // who orbits the light after a split

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

  /** Sends audio or text to the agent, then plays its steps in, then the reply, then balances move. */
  const send = useCallback(async (input: { audio: Blob } | { text: string }, shown: string) => {
    clearTimers()
    setHeard(shown)
    setReply('')
    setSteps([])
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
    let t = 0
    r.steps.forEach((s) => {
      t += 220
      later(() => setSteps((cur) => [...cur, s]), t)
    })

    later(() => {
      setRunning(false)
      setOrb(r.asking ? 'ask' : 'reply')
      say(r.reply)
      setSplitWith(r.split_with)
      setPeople(r.people)
      if (r.receipt) {
        setReceipt(r.receipt)
        setHistory((h) => [...h, { heard: r.transcript, steps: r.steps, receipt: r.receipt! }])
      }
      if (!r.asking) later(() => setOrb((o) => (o === 'reply' ? 'idle' : o)), 9000)
    }, t + 300)
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
    if (orb === 'listening') return onAudio(await mic.stop())
    clearTimers()
    setHeard('')
    setReply('')
    setSteps([])
    setReceipt(null)
    setOrb('listening')
    mic.start()
  }, [orb, running, mic, onAudio])

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
    send({ text }, text)
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
            placeholder={orb === 'ask' ? 'or type your answer…' : 'or type it…'}
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
