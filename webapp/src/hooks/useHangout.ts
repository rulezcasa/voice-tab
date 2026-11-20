import { useCallback, useMemo, useState } from 'react'
import * as api from '../lib/api'
import { centroid, distance, reachMetres } from '../lib/geo'
import type { GroupBalance, HangoutMember, HangoutResult, LngLat, PlaceKind } from '../lib/types'

/** Per-person colours on the map and in the panel; "you" always get the first. */
export const MEMBER_COLORS = ['#3d7bff', '#10a87a', '#ff6a2b', '#9a4dff', '#e0a400', '#ec3f86', '#0ea0c6', '#5aa521']

export type HangoutStatus = 'idle' | 'searching' | 'done' | 'error'

const DEFAULTS = { budget: '30', minutes: 10, mode: 'walk' as const }

/** All hangout planning state, shared by the side panel and the map. */
export function useHangout() {
  const [groups, setGroups] = useState<GroupBalance[]>([])
  const [groupId, setGroupId] = useState<number | null>(null)
  const [members, setMembers] = useState<HangoutMember[]>([])
  const [kinds, setKinds] = useState<PlaceKind[]>(['restaurant'])
  const [note, setNote] = useState('')
  const [placing, setPlacing] = useState<number | null>(null) // person id waiting for a map tap
  const [status, setStatus] = useState<HangoutStatus>('idle')
  const [error, setError] = useState('')
  const [result, setResult] = useState<HangoutResult | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const loadGroups = useCallback(
    () =>
      api
        .groupBalances()
        .then((gs) => setGroups(gs.filter((g) => g.id !== null)))
        .catch(() => {}),
    [],
  )

  const clearResult = () => {
    setResult(null)
    setSelected(null)
    setStatus('idle')
  }

  const pickGroup = (g: GroupBalance) => {
    setGroupId(g.id)
    setMembers((prev) =>
      g.people.map((p) => {
        const kept = prev.find((m) => m.person_id === p.id) // keep settings for people already set up
        return kept ?? { person_id: p.id, name: p.name, is_me: p.is_me, going: true, location: null, ...DEFAULTS }
      }),
    )
    clearResult()
  }

  const update = (id: number, patch: Partial<HangoutMember>) => {
    setMembers((ms) => ms.map((m) => (m.person_id === id ? { ...m, ...patch } : m)))
    if (result) clearResult() // results no longer match what's on screen
  }

  const place = (id: number, at: LngLat) => {
    update(id, { location: at })
    setPlacing(null)
  }

  const toggleKind = (k: PlaceKind) => {
    setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]))
    if (result) clearResult()
  }

  const going = useMemo(() => members.filter((m) => m.going), [members])
  // people whose reach doesn't cover the group's middle: a hint before searching, not a blocker
  const outOfReach = useMemo(() => {
    const placed = going.filter((m) => m.location)
    if (placed.length < 2) return []
    const mid = centroid(placed.map((m) => m.location!))
    return placed.filter((m) => distance(m.location!, mid) > reachMetres(m.minutes, m.mode))
  }, [going])

  const ready = going.length >= 2 && going.every((m) => m.location && Number(m.budget) > 0)

  const search = async () => {
    if (!ready) return
    setStatus('searching')
    setError('')
    setSelected(null)
    try {
      const r = await api.hangout({
        group_id: groupId,
        members: going.map(({ person_id, name, is_me, budget, minutes, mode, location }) => ({ person_id, name, is_me, budget, minutes, mode, location })),
        kinds,
        note: note.trim(),
      })
      setResult(r)
      setStatus('done')
    } catch (e) {
      setError((e as Error).message)
      setStatus('error')
    }
  }

  const colorOf = (id: number) => {
    const i = members.findIndex((m) => m.person_id === id)
    return MEMBER_COLORS[(i < 0 ? 0 : i) % MEMBER_COLORS.length]
  }

  return {
    groups, loadGroups, groupId, pickGroup,
    members, going, outOfReach, update, colorOf,
    placing, setPlacing, place,
    kinds, toggleKind, note, setNote,
    ready, search, status, error, result, selected, setSelected, clearResult,
  }
}

export type Hangout = ReturnType<typeof useHangout>
