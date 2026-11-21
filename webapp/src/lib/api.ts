// Backend calls. Vite proxies /api to FastAPI on :8000 (see vite.config.ts).
import { mockHangout } from './mockHangout'
import type { Activity, GroupBalance, HangoutRequest, HangoutResult, LngLat, Person, Receipt, TrailStep } from './types'

export interface IngestResult {
  transcript: string
  reply: string
  steps: TrailStep[]
  receipt: Receipt | null
  split_with: string[] // names (not me) in the expense that was just saved
  asking: boolean // the agent asked a question and is waiting for the answer
  people: Person[] // everyone's balance after this run
}

/** The database clock is UTC and its timestamps carry no zone: mark them so the browser shows local time. */
export const utc = (iso: string) => (/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

const EXT: Record<string, string> = { webm: 'webm', mp4: 'm4a', ogg: 'ogg', wav: 'wav', mpeg: 'mp3' }

/** Send what was said (audio) or typed (text). The session lets the agent ask follow-up questions. */
export async function ingest(input: { audio: Blob } | { text: string }, sessionId: string): Promise<IngestResult> {
  const form = new FormData()
  form.append('session_id', sessionId)
  if ('audio' in input) {
    const sub = input.audio.type.split(';')[0].split('/')[1] ?? 'webm'
    form.append('audio', input.audio, `speech.${EXT[sub] ?? 'webm'}`)
  } else {
    form.append('text', input.text)
  }
  const r: IngestResult = await json(await fetch('/api/ingest', { method: 'POST', body: form }))
  if (r.receipt) r.receipt.logged_at = utc(r.receipt.logged_at)
  return r
}

export async function balances(): Promise<Person[]> {
  return json(await fetch('/api/balances'))
}

export async function groupBalances(): Promise<GroupBalance[]> {
  return json(await fetch('/api/balances/groups'))
}

/** New group; I'm added as a member automatically. Throws with the server's message on a bad name. */
export async function createGroup(name: string, memberIds: number[]): Promise<{ id: number; name: string }> {
  return json(
    await fetch('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, member_ids: memberIds }),
    }),
  )
}

interface ApiExpense {
  description: string
  amount: string
  category: string
  group_name: string | null
  spent_on: string
  created_at: string
  shares: { name: string; is_me: boolean; paid: string; owed: string }[]
}

/** Recent expenses as Activity, oldest first (the sheet shows newest first). No transcript is stored. */
export async function history(limit = 30): Promise<Activity[]> {
  const rows: ApiExpense[] = await json(await fetch(`/api/expenses?limit=${limit}`))
  return rows.reverse().map((e) => ({
    heard: e.description,
    steps: [],
    receipt: {
      description: e.description,
      amount: e.amount,
      category: e.category,
      group: e.group_name,
      spent_on: e.spent_on,
      logged_at: utc(e.created_at),
      shares: e.shares.map(({ name, is_me, paid, owed }) => ({ name, is_me, paid, owed })),
    },
  }))
}

/**
 * Places that fit the group. Uses POST /api/hangout once the backend has it; until then
 * (404, or no backend running) it falls back to a local mock so the UI can be built and demoed.
 */
export async function hangout(req: HangoutRequest): Promise<HangoutResult> {
  let res: Response
  try {
    res = await fetch('/api/hangout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
  } catch {
    return mockHangout(req)
  }
  // 404/405 = route not built yet; a non-JSON error = the dev proxy couldn't reach the backend
  if (res.status === 404 || res.status === 405 || (!res.ok && !res.headers.get('content-type')?.includes('json'))) return mockHangout(req)
  return json(res)
}

// ---------- multi-agent meetups: each person's agent answers for them, privately ----------

export interface AgentMessage {
  round: number
  from: string // "coordinator" or a person's name (their agent)
  to?: string
  text: string
  decision?: 'accept' | 'decline'
  hint?: string
  venue?: string
  event?: 'left' | 'replanned'
  by?: string // live plans: who answered (agent, approved / Priya, changed / agent (no reply in time) ...)
}

export interface Negotiation {
  id?: number
  group: { id: number; name: string }
  status: 'agreed' | 'no_agreement' | 'no_time' | 'no_venue' | 'no_people' | 'waiting'
  reason: string | null
  agreed: {
    venue: { id: number; name: string; kind: string; indoor: boolean; lng: number; lat: number; description?: string | null }
    starts_at: string
    ends_at: string
  } | null
  rounds: number
  members: string[]
  transcript: AgentMessage[]
  model_calls: number
  /** What each personal agent shares with the coordinator: rough area ([lat, lng], ~1 km), travel mode. */
  shared: { person_id: number; name: string; area: [number, number]; mode: string }[]
}

/** Coordinator + personal agents negotiate in rounds. Nobody's budget or home leaves their own agent. */
export async function negotiate(groupId: number, start: string, end: string, activity: string): Promise<Negotiation> {
  return json(
    await fetch('/api/meetups/negotiate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId, start, end, activity: activity || null }),
    }),
  )
}

export interface MyProfile {
  home: LngLat | null
  budget: string | null
  radius_mi: number | null
  max_travel_min: number | null
  travel_mode: 'walk' | 'bike' | 'transit' | 'drive' | null
  interests: string[]
}

export interface MyAgent {
  person: { id: number; name: string }
  profile: MyProfile
  busy: { id: number; starts_at: string; ends_at: string; label: string }[]
  groups: string[]
}

export interface MyNegotiation extends Negotiation {
  at: string
  you: string
  your_agent: { round: number; venue?: string; ok?: boolean; reason?: string | null; travel_min?: number; total?: string; decision?: string; change?: Record<string, unknown> }[]
}

const me = (token: string, path = '') => `/api/me/${encodeURIComponent(token)}${path}`
const send = (method: string, body: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const myAgent = async (token: string): Promise<MyAgent> => json(await fetch(me(token)))
export const updateMyProfile = async (token: string, p: Partial<MyProfile>): Promise<MyAgent> =>
  json(await fetch(me(token, '/profile'), send('PUT', p)))
export const addMyBusy = async (token: string, starts_at: string, ends_at: string, label: string): Promise<MyAgent> =>
  json(await fetch(me(token, '/busy'), send('POST', { starts_at, ends_at, label })))
export const removeMyBusy = async (token: string, id: number): Promise<MyAgent> =>
  json(await fetch(me(token, `/busy/${id}`), { method: 'DELETE' }))
export const myAgentActivity = async (token: string): Promise<MyNegotiation[]> => json(await fetch(me(token, '/agent')))

// ---------- live plans: agents draft, people (or seeded bots) answer ----------

export interface LivePlan extends Negotiation {
  id: number
  started_at: string
  waiting_on: string[]
  seconds_left: number | null
  proposal: { venue: string; starts_at: string; ends_at: string } | null
  players: Record<string, string> // name -> "you" | "bot (picky)" | "person"
  seed: number | null
  player_token?: string
}

export interface MyLivePlan extends LivePlan {
  you: string
  your_turn: {
    draft: { decision: 'accept' | 'decline'; message: string; hint: string }
    facts: { ok: boolean; reason: string | null; travel_min: number; total: string }
  } | null
  you_answered: boolean
  you_left: boolean
}

export type LiveAction = 'approve' | 'accept' | 'decline' | 'leave'

export async function startLive(
  groupId: number, start: string, end: string, activity: string,
  opts: { bots: boolean; seed?: number | null; playAs?: number | null; replyWindowS?: number },
): Promise<LivePlan> {
  return json(await fetch('/api/meetups/live', send('POST', {
    group_id: groupId, start, end, activity: activity || null,
    bots: opts.bots, seed: opts.seed ?? null, play_as: opts.playAs ?? null, reply_window_s: opts.replyWindowS ?? 180,
  })))
}
export const getLive = async (id: number): Promise<LivePlan> => json(await fetch(`/api/meetups/live/${id}`))
export const stopWaiting = async (id: number): Promise<LivePlan> => json(await fetch(`/api/meetups/live/${id}/stop-waiting`, { method: 'POST' }))
export const myLive = async (token: string): Promise<MyLivePlan[]> => json(await fetch(me(token, '/live')))
export const respondLive = async (token: string, id: number, action: LiveAction, message?: string, hint?: string): Promise<MyLivePlan> =>
  json(await fetch(me(token, `/live/${id}/respond`), send('POST', { action, message: message || null, hint: hint || null })))

/** Ask the group in your own words ("guys hang out tomm?"): the coordinator works out when and what, and the
 *  game starts with your message first in the chat. You play yourself; everyone else is a bot. */
export async function askFriends(groupId: number, message: string, playAs: number | null): Promise<LivePlan & { understood?: Record<string, unknown> }> {
  return json(await fetch('/api/meetups/live', send('POST', {
    group_id: groupId, message, bots: true, play_as: playAs, hands_off: true, reply_window_s: 120,
  })))
}
