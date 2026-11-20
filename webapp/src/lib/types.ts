// UI data shapes. Money is a string ("13.33") so cents stay exact, matching the backend.

export type OrbState = 'idle' | 'listening' | 'thinking' | 'reply' | 'ask'

export interface Person {
  id: number
  name: string
  is_me: boolean
  net: string // positive = is owed money, negative = owes
}

/** Balances inside one group. id null = the "Non-group" bucket. */
export interface GroupBalance {
  id: number | null
  name: string
  net: string // my net in this group
  people: Person[]
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

// ---------- hangout: the agent suggests places that fit a group's budgets and reach ----------

export type LngLat = [number, number] // [lng, lat], the order MapLibre and GeoJSON use
export type TravelMode = 'walk' | 'bike' | 'drive'
export type PlaceKind = 'restaurant' | 'cafe' | 'bar' | 'retail' | 'activity'

/** One person in a hangout plan, as set in the panel. */
export interface HangoutMember {
  person_id: number
  name: string
  is_me: boolean
  going: boolean
  budget: string // per person, dollars ("30")
  minutes: number // how far they'll travel
  mode: TravelMode
  location: LngLat | null
}

/** What the UI sends to the recommender. */
export interface HangoutRequest {
  group_id: number | null
  members: Omit<HangoutMember, 'going'>[] // only the people going, each with a location
  kinds: PlaceKind[]
  note: string // free text: "vegetarian", "somewhere quiet"...
}

export interface HangoutPlace {
  id: string
  name: string
  kind: PlaceKind
  location: LngLat
  address: string
  price_level: 1 | 2 | 3 | 4
  per_person: string // estimated spend per person, dollars
  rating: number | null
  minutes: Record<number, number> // person_id -> travel minutes
  why: string // one line on why it fits
}

export interface HangoutResult {
  meeting_point: LngLat
  places: HangoutPlace[]
}
