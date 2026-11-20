// UI data shapes. Money is a string ("13.33") so cents stay exact, matching the backend.

export type OrbState = 'idle' | 'listening' | 'thinking' | 'reply' | 'ask'

export interface Person {
  id: number
  name: string
  is_me: boolean
  net: string // positive = is owed money, negative = owes
}

export interface TrailStep {
  step: string // route, extract, resolve...
  say: string // plain-language version for people
  model: string | null
  detail: string // technical detail for the "how" view
  ms: number
}

/** What got logged, in human terms: the card shown after a run. */
export interface Receipt {
  description: string
  amount: string
  category: string
  group: string | null
  spent_on: string // YYYY-MM-DD
  logged_at: string // ISO timestamp
  shares: { name: string; is_me: boolean; paid: string; owed: string }[]
}

export interface Activity {
  heard: string
  steps: TrailStep[]
  receipt: Receipt
}
