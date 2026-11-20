// Static placeholder data for the dummy UI. Replaced by API calls later.
import type { Activity, Person, Receipt, TrailStep } from './types'
import { isoDay } from './format'

const ago = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return isoDay(d)
}

export const PEOPLE: Person[] = [
  { id: 1, name: 'Harish', is_me: true, net: '111.64' },
  { id: 2, name: 'Nikhil', is_me: false, net: '-1.71' },
  { id: 3, name: 'Harinee', is_me: false, net: '-82.61' },
  { id: 4, name: 'Sipagan', is_me: false, net: '18.98' },
  { id: 5, name: 'Alex Chen', is_me: false, net: '-29.30' },
  { id: 6, name: 'Alex Park', is_me: false, net: '-17.00' },
]

const at = (days: number, h: number, m: number) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  d.setHours(h, m, 0, 0)
  return d.toISOString()
}

const me = (paid: string, owed: string) => ({ name: 'Harish', is_me: true, paid, owed })
const them = (name: string, owed: string) => ({ name, is_me: false, paid: '0.00', owed })

/** Past things you told Tab, oldest first (Activity shows newest first). No steps: "How" stays hidden. */
export const HISTORY: Activity[] = [
  {
    heard: 'Dish soap and paper towels at Target, 18.45, split with the roommates',
    steps: [],
    receipt: { description: 'dish soap and paper towels', amount: '18.45', category: 'household', group: 'Apt 4B', spent_on: ago(13), logged_at: at(13, 19, 12), shares: [me('18.45', '6.15'), them('Nikhil', '6.15'), them('Harinee', '6.15')] },
  },
  {
    heard: 'Concert tickets were 120, half with Alex Park',
    steps: [],
    receipt: { description: 'concert tickets', amount: '120.00', category: 'entertainment', group: null, spent_on: ago(11), logged_at: at(11, 21, 40), shares: [me('120.00', '60.00'), them('Alex Park', '60.00')] },
  },
  {
    heard: 'Dinner at Nopa, 96, with Sipagan and Alex Chen',
    steps: [],
    receipt: { description: 'dinner', amount: '96.00', category: 'dining', group: null, spent_on: ago(6), logged_at: at(6, 22, 5), shares: [me('96.00', '32.00'), them('Sipagan', '32.00'), them('Alex Chen', '32.00')] },
  },
  {
    heard: '64.30 at Trader Joe’s, split with my roommates',
    steps: [],
    receipt: { description: 'groceries', amount: '64.30', category: 'groceries', group: 'Apt 4B', spent_on: ago(3), logged_at: at(3, 18, 27), shares: [me('64.30', '21.44'), them('Nikhil', '21.43'), them('Harinee', '21.43')] },
  },
  {
    heard: 'Uber to the office, 18.40',
    steps: [],
    receipt: { description: 'Uber to the office', amount: '18.40', category: 'transport', group: null, spent_on: ago(2), logged_at: at(2, 9, 14), shares: [me('18.40', '18.40')] },
  },
  {
    heard: 'Spent 20 on a cab',
    steps: [],
    receipt: { description: 'cab', amount: '20.00', category: 'transport', group: null, spent_on: ago(1), logged_at: at(1, 18, 42), shares: [me('20.00', '20.00')] },
  },
]

/** One canned run of the pipeline, played back step by step after you talk or type. */
export const DEMO_RUN = {
  heard: 'I paid 40 bucks for groceries today, split with my roommates.',
  steps: [
    { step: 'transcribe', say: 'Heard you', model: 'whisper-large-v3-turbo', detail: '"I paid 40 bucks for groceries…"', ms: 412 },
    { step: 'route', say: 'Logging a new expense', model: 'gliclass-instruct-large', detail: 'log · 0.97', ms: 118 },
    { step: 'extract', say: '$40 for groceries, today', model: 'gliner2-large', detail: '$40.00 · groceries · today', ms: 186 },
    { step: 'classify', say: 'Filed under Groceries', model: 'gliclass-instruct-large', detail: 'groceries · 0.94', ms: 96 },
    { step: 'resolve', say: 'Roommates → Nikhil & Harinee', model: 'singlestore', detail: 'roommates → Nikhil, Harinee', ms: 41 },
    { step: 'math', say: 'Split three ways', model: null, detail: '13.34 / 13.33 / 13.33', ms: 1 },
    { step: 'store', say: 'Saved to Apt 4B', model: 'singlestore', detail: 'expense #28 · Apt 4B', ms: 33 },
    { step: 'balances', say: 'Balances updated', model: 'singlestore', detail: '3 people updated', ms: 27 },
  ] satisfies TrailStep[],
  reply: 'Got it. $40 on groceries, split three ways. Nikhil and Harinee each owe you $13.33.',
  receipt: {
    description: 'groceries',
    amount: '40.00',
    category: 'groceries',
    group: 'Apt 4B',
    shares: [
      { name: 'Harish', is_me: true, paid: '40.00', owed: '13.34' },
      { name: 'Nikhil', is_me: false, paid: '0.00', owed: '13.33' },
      { name: 'Harinee', is_me: false, paid: '0.00', owed: '13.33' },
    ],
  } satisfies Omit<Receipt, 'spent_on' | 'logged_at'>,
  deltas: { Harish: '26.66', Nikhil: '-13.33', Harinee: '-13.33' } as Record<string, string>,
}
