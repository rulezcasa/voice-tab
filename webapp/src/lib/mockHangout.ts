// Stand-in for the recommender while it's being built. Scatters plausible places around the
// group's middle, keeps the ones everyone can reach on budget, and ranks by total travel time.
// Delete once POST /api/hangout exists (api.hangout() switches over by itself).
import { centroid, offset, reachMetres, travelMinutes } from './geo'
import type { HangoutPlace, HangoutRequest, HangoutResult, PlaceKind } from './types'

const NAMES: Record<PlaceKind, string[]> = {
  restaurant: ['Little Saffron', 'Ember & Oak', 'Noodle Bar 88', 'Casa Verde', 'The Copper Pot', 'Miso Hungry', 'Fig Tree Kitchen'],
  cafe: ['Grain Coffee', 'Paper Plane Café', 'Slow Pour', 'Morning Glory', 'Two Birds Espresso'],
  bar: ['The Low Light', 'Hop Yard', 'Velvet Room', 'Corner Tap', 'Night Owl Lounge'],
  retail: ['Common Goods', 'Thread & Co.', 'Paperback Alley', 'Market Hall', 'Vinyl Underground'],
  activity: ['Pin Palace Bowling', 'Escape Room 42', 'Glow Mini Golf', 'Cue Club Billiards', 'Arcade Nine'],
}

const STREETS = ['Market St', 'Oak Ave', 'Mission St', 'Pine St', 'Valencia St', 'Hayes St', 'Grove St', 'Castro St']

const PRICE: Record<1 | 2 | 3 | 4, [number, number]> = { 1: [8, 15], 2: [15, 30], 3: [30, 55], 4: [55, 90] }

const WHY: Record<PlaceKind, string[]> = {
  restaurant: ['Big tables, takes groups without a booking', 'Shareable plates keep the bill even', 'Quick service, good for a weeknight'],
  cafe: ['Quiet enough to talk', 'Lots of seating, open late', 'Great pastries, cheap'],
  bar: ['Happy hour until 7', 'Room to stand around in a group', 'Board games on the shelf'],
  retail: ['Lots of small shops on one block', 'Something for everyone to browse', 'Weekend market stalls'],
  activity: ['Book a lane for the group', 'Splits well, priced per person', 'Fun even if not everyone eats'],
}

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]

export async function mockHangout(req: HangoutRequest): Promise<HangoutResult> {
  await new Promise((r) => setTimeout(r, 900 + Math.random() * 600)) // feel like a real call

  const members = req.members.filter((m) => m.location)
  const middle = centroid(members.map((m) => m.location!))
  const kinds: PlaceKind[] = req.kinds.length ? req.kinds : ['restaurant', 'cafe', 'bar']
  const budget = Math.min(...members.map((m) => Number(m.budget) || Infinity))
  // look around the middle as far as the furthest reach; anything someone can't reach is skipped
  const radius = Math.max(...members.map((m) => reachMetres(m.minutes, m.mode)))

  const used = new Set<string>()
  const candidates: HangoutPlace[] = []
  for (let tries = 0; tries < 400 && candidates.length < 10; tries++) {
    const location = offset(middle, Math.sqrt(Math.random()) * radius, Math.random() * 360)
    const minutes = Object.fromEntries(members.map((m) => [m.person_id, Math.max(1, Math.round(travelMinutes(m.location!, location, m.mode)))]))
    if (!members.every((m) => minutes[m.person_id] <= m.minutes)) continue // someone can't get there in time
    const kind = kinds[candidates.length % kinds.length]
    const name = NAMES[kind].find((n) => !used.has(n))
    if (!name) continue
    used.add(name)
    const price_level = (1 + Math.floor(Math.random() * 3)) as 1 | 2 | 3
    const [lo, hi] = PRICE[price_level]
    candidates.push({
      id: `${kind}-${tries}`,
      name,
      kind,
      location,
      address: `${100 + Math.floor(Math.random() * 1800)} ${pick(STREETS)}`,
      price_level,
      per_person: (lo + Math.random() * (hi - lo)).toFixed(0),
      rating: Math.round((3.8 + Math.random() * 1.1) * 10) / 10,
      minutes,
      why: pick(WHY[kind]),
    })
  }

  const fits = (p: HangoutPlace) => Number(p.per_person) <= budget
  const total = (p: HangoutPlace) => Object.values(p.minutes).reduce((a, b) => a + b, 0)

  return { meeting_point: middle, places: candidates.filter(fits).sort((a, b) => total(a) - total(b)).slice(0, 6) }
}
