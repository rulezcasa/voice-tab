// Backend calls. Vite proxies /api to FastAPI on :8000 (see vite.config.ts).
import { mockHangout } from './mockHangout'
import type { Activity, GroupBalance, HangoutRequest, HangoutResult, Person, Receipt, TrailStep } from './types'

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
