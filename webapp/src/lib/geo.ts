// Small geometry helpers for the hangout map. Distances are straight-line estimates;
// the real recommender can swap reach circles for isochrones without the UI changing.
import type { LngLat, TravelMode } from './types'

/** Rough city speeds, metres per minute. */
export const SPEED: Record<TravelMode, number> = { walk: 80, bike: 250, drive: 450 }

export const reachMetres = (minutes: number, mode: TravelMode) => minutes * SPEED[mode]

const R = 6371008.8 // earth radius, metres
const rad = (d: number) => (d * Math.PI) / 180
const deg = (r: number) => (r * 180) / Math.PI

export function distance([lng1, lat1]: LngLat, [lng2, lat2]: LngLat): number {
  const dLat = rad(lat2 - lat1)
  const dLng = rad(lng2 - lng1)
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

/** The point `metres` away from `from` heading `bearing` degrees (0 = north). */
export function offset([lng, lat]: LngLat, metres: number, bearing: number): LngLat {
  const d = metres / R
  const b = rad(bearing)
  const la1 = rad(lat)
  const la2 = Math.asin(Math.sin(la1) * Math.cos(d) + Math.cos(la1) * Math.sin(d) * Math.cos(b))
  const lo2 = rad(lng) + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la1), Math.cos(d) - Math.sin(la1) * Math.sin(la2))
  return [deg(lo2), deg(la2)]
}

/** A circle as a GeoJSON ring (closed). */
export function circle(center: LngLat, metres: number, steps = 72): LngLat[] {
  const ring = Array.from({ length: steps }, (_, i) => offset(center, metres, (i * 360) / steps))
  return [...ring, ring[0]]
}

/** Plain average of the points; good enough as a "middle" for a city-sized group. */
export function centroid(points: LngLat[]): LngLat {
  const n = points.length
  return [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n]
}

export const travelMinutes = (a: LngLat, b: LngLat, mode: TravelMode) => distance(a, b) / SPEED[mode]
