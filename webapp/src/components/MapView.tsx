import { AttributionControl, GeolocateControl, LngLatBounds, Map as MapLibre, Marker, NavigationControl, setWorkerUrl, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Hangout } from '../hooks/useHangout'
import { circle, reachMetres } from '../lib/geo'
import { figureOf, KIND_EMOJI, MODE_EMOJI } from '../lib/emoji'
import type { LngLat } from '../lib/types'

// OpenFreeMap: free vector tiles, no key. Light "positron" base, recoloured into a sunny toy town.
const STYLE = 'https://tiles.openfreemap.org/styles/positron'
const VIEW_KEY = 'tab.map.view'
const FALLBACK = { center: [-122.4194, 37.7749] as LngLat, zoom: 12.5 } // San Francisco until we know better

const TINT: [string, string, unknown][] = [
  ['background', 'background-color', '#f1e9da'],
  ['landuse_residential', 'fill-color', '#ece2d0'],
  ['park', 'fill-color', '#a9d18e'],
  ['landcover_wood', 'fill-color', '#8fc479'],
  ['water', 'fill-color', '#4fa3e0'],
  ['waterway', 'line-color', '#4fa3e0'],
  ['building', 'fill-color', '#e6d8c0'],
  ['building', 'fill-outline-color', '#cdb894'],
  ['road_area_pier', 'fill-color', '#e8dcc6'],
  ['highway_path', 'line-color', '#d9c9ab'],
  ['highway_minor', 'line-color', '#fffaf0'],
  ['highway_major_casing', 'line-color', '#c9b28b'],
  ['highway_major_inner', 'line-color', '#fffdf6'],
  ['highway_major_subtle', 'line-color', '#d8c6a4'],
  ['highway_motorway_casing', 'line-color', '#c99a5b'],
  ['highway_motorway_inner', 'line-color', '#ffe3a8'],
  ['highway_motorway_subtle', 'line-color', '#e2b978'],
  ['highway_motorway_bridge_casing', 'line-color', '#c99a5b'],
  ['highway_motorway_bridge_inner', 'line-color', '#ffe3a8'],
  ['railway', 'line-color', '#b9a588'],
  ['railway_transit', 'line-color', '#b9a588'],
  ['water_name_point_label', 'text-color', '#1d5f99'],
  ['water_name_line_label', 'text-color', '#1d5f99'],
]

// Pastel facades, varied building to building like a model town. Tiles carry no stable id for
// every building, so mix the id (when present) with its height to pick a colour.
const FACADES = ['#f4d6a6', '#f2c6b4', '#cfe3c1', '#c9dcef', '#f6e7b8', '#e3d0ec', '#f5d9c4', '#d8e8e0']
const pick = ['%', ['+', ['coalesce', ['id'], 0], ['round', ['*', ['coalesce', ['get', 'render_height'], 4], 7]]], FACADES.length]
const FACADE_COLOR = ['match', pick, ...FACADES.slice(0, -1).flatMap((c, i) => [i, c]), FACADES.at(-1)]

// Snappy, alive camera: tilted for 3D buildings, a little turn on big moves.
const PITCH = 55
const BEARING = -35 // turned off-grid so blocks read as a diorama
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Overshoots a touch then settles, like a spring. */
const easeOutBack = (t: number) => 1 + 2.2 * (t - 1) ** 3 + 1.2 * (t - 1) ** 2

// "Marching ants" for the lines to the meeting spot: MapLibre can't animate dash offset,
// so we step through dash patterns that look like the dashes sliding along.
const ANTS: number[][] = [
  [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
]

// MapLibre finds its worker next to its own file, which Vite's dep bundling moves; point at it directly.
setWorkerUrl(workerUrl)

const empty = { type: 'FeatureCollection' as const, features: [] }

function savedView() {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY) ?? '')
    if (Array.isArray(v.center) && typeof v.zoom === 'number') return v as typeof FALLBACK
  } catch {
    /* no saved view */
  }
  return FALLBACK
}

/** Room left for the map when the hangout panel covers part of the screen. */
function padding(panelOpen: boolean) {
  const wide = window.matchMedia('(min-width: 860px)').matches
  const base = 72
  if (!panelOpen) return { top: base, bottom: base + 60, left: base, right: base }
  return wide
    ? { top: base, bottom: base, left: 420 + base, right: base }
    : { top: base, bottom: Math.round(window.innerHeight * 0.58), left: 40, right: 40 }
}

export function MapView({ hangout, panelOpen }: { hangout: Hangout; panelOpen: boolean }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibre | null>(null)
  const [loaded, setLoaded] = useState(false)
  const h = useRef(hangout) // marker/map handlers always see the latest state
  const panel = useRef(panelOpen)
  useLayoutEffect(() => {
    h.current = hangout
    panel.current = panelOpen
  })

  const people = useRef(new Map<number, Marker>())
  const places = useRef(new Map<string, Marker>())
  const middle = useRef<Marker | null>(null)
  const radii = useRef(new Map<number, number>()) // reach radius currently drawn, per person (for tweening)
  const live = useRef(new Map<number, LngLat>()) // where a pin is mid-drag, so its circle follows
  const targets = useRef<{ id: number; at: LngLat; r: number; color: string }[]>([])
  const reachRaf = useRef(0)

  /** Draws every reach circle at its current (tweened) radius and live position. */
  const drawReach = () => {
    const src = map.current?.getSource('reach') as GeoJSONSource | undefined
    src?.setData({
      type: 'FeatureCollection',
      features: targets.current.map((t) => ({
        type: 'Feature' as const,
        properties: { color: t.color },
        geometry: { type: 'Polygon' as const, coordinates: [circle(live.current.get(t.id) ?? t.at, Math.max(1, radii.current.get(t.id) ?? 0))] },
      })),
    })
  }

  // ---- create the map once ----
  useEffect(() => {
    const view = savedView()
    const m = new MapLibre({
      container: el.current!,
      style: STYLE,
      center: view.center,
      zoom: reduced() ? view.zoom : view.zoom - 2.5,
      pitch: reduced() ? PITCH : 0,
      bearing: reduced() ? BEARING : 0,
      attributionControl: false,
      maxPitch: 70,
    })
    // bottom-right belongs to the orb, top-left to the panel
    m.addControl(new AttributionControl({ compact: true }), 'bottom-left')
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: false }), 'top-right')

    m.on('load', () => {
      for (const [layer, prop, value] of TINT) {
        if (m.getLayer(layer)) m.setPaintProperty(layer, prop as never, value as never)
      }

      // 3D buildings that rise out of the ground as you zoom in, under the labels
      const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id
      m.addLayer(
        {
          id: 'building-3d',
          type: 'fill-extrusion',
          source: 'openmaptiles',
          'source-layer': 'building',
          minzoom: 13.5,
          paint: {
            'fill-extrusion-color': FACADE_COLOR as never,
            'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 13.5, 0, 15, ['coalesce', ['get', 'render_height'], 0]],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
            'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13.5, 0, 14.5, 0.95],
            'fill-extrusion-vertical-gradient': true, // darker at the base, like soft ambient shade
          },
        },
        firstLabel,
      )

      // a bright day sky with a hazy horizon when tilted
      m.setLight({ anchor: 'map', position: [1.4, 200, 50], color: '#fff6e5', intensity: 0.45 })
      m.setSky({
        'sky-color': '#9fd3ff',
        'horizon-color': '#fdf3e1',
        'fog-color': '#f1e9da',
        'sky-horizon-blend': 0.6,
        'horizon-fog-blend': 0.7,
        'fog-ground-blend': 0.4,
        'atmosphere-blend': 0,
      })

      m.addSource('reach', { type: 'geojson', data: empty })
      m.addSource('links', { type: 'geojson', data: empty })
      m.addLayer({ id: 'reach-fill', type: 'fill', source: 'reach', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.08 } })
      m.addLayer({
        id: 'reach-line',
        type: 'line',
        source: 'reach',
        paint: { 'line-color': ['get', 'color'], 'line-opacity': 0.95, 'line-width': 2, 'line-dasharray': [2, 1.5] },
      })
      m.addLayer({
        id: 'links',
        type: 'line',
        source: 'links',
        layout: { 'line-cap': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-opacity': 1, 'line-width': 3, 'line-dasharray': ANTS[0] },
      })
      setLoaded(true)

      // fly in from above
      if (!reduced()) m.flyTo({ center: view.center, zoom: view.zoom, pitch: PITCH, bearing: BEARING, duration: 2600, curve: 1.2, essential: true })
    })

    // figures shrink as you zoom out so a crowd stays readable
    const sizePins = () => {
      const k = Math.min(1, Math.max(0.5, (m.getZoom() - 10.5) / 4))
      el.current?.style.setProperty('--ps', k.toFixed(3))
    }
    m.on('zoom', sizePins)
    sizePins()

    m.on('click', (e) => {
      const id = h.current.placing
      if (id !== null) h.current.place(id, [e.lngLat.lng, e.lngLat.lat])
    })

    m.on('moveend', () => {
      try {
        const c = m.getCenter()
        localStorage.setItem(VIEW_KEY, JSON.stringify({ center: [c.lng, c.lat], zoom: m.getZoom() }))
      } catch {
        /* storage unavailable */
      }
    })

    map.current = m
    const pins = people.current
    const pois = places.current
    return () => {
      m.remove()
      map.current = null
      pins.clear()
      pois.clear()
      middle.current = null
      setLoaded(false)
    }
  }, [])

  const { members, going, result, selected, placing } = hangout

  // ---- people: a draggable pin each, plus their reach circle ----
  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return
    const seen = new Set<number>()
    for (const p of going) {
      if (!p.location) continue
      seen.add(p.person_id)
      let mk = people.current.get(p.person_id)
      if (!mk) {
        const node = document.createElement('div')
        node.className = 'pin'
        node.innerHTML = '<span class="pin-fig"></span><span class="pin-mode"></span><span class="pin-name"></span>'
        node.style.setProperty('--d', `${(-Math.random() * 3).toFixed(2)}s`) // so pins don't bob in sync
        // anchored at the feet, so the figure stands on the spot
        mk = new Marker({ element: node, draggable: true, anchor: 'bottom' }).setLngLat(p.location).addTo(m)
        const id = p.person_id
        const marker = mk
        marker.on('dragstart', () => node.classList.add('lifted'))
        marker.on('drag', () => {
          const at = marker.getLngLat()
          live.current.set(id, [at.lng, at.lat])
          drawReach()
        })
        marker.on('dragend', () => {
          const at = marker.getLngLat()
          live.current.delete(id)
          node.classList.remove('lifted')
          node.classList.add('landed')
          setTimeout(() => node.classList.remove('landed'), 500)
          h.current.update(id, { location: [at.lng, at.lat] })
        })
        people.current.set(id, mk)
      }
      const node = mk.getElement()
      node.style.setProperty('--c', h.current.colorOf(p.person_id))
      node.querySelector('.pin-fig')!.textContent = figureOf(p.person_id, p.is_me)
      node.querySelector('.pin-mode')!.textContent = MODE_EMOJI[p.mode]
      node.querySelector('.pin-name')!.textContent = p.is_me ? 'you' : p.name.split(' ')[0]
      node.classList.toggle('me', p.is_me)
      mk.setLngLat(p.location)
    }
    for (const [id, mk] of people.current) {
      if (!seen.has(id)) {
        mk.remove()
        people.current.delete(id)
      }
    }

    // reach circles grow out from the pin (or to their new size) with a little spring
    targets.current = going
      .filter((p) => p.location)
      .map((p) => ({ id: p.person_id, at: p.location!, r: reachMetres(p.minutes, p.mode), color: h.current.colorOf(p.person_id) }))
    for (const id of radii.current.keys()) if (!seen.has(id)) radii.current.delete(id)
    const from = new Map(radii.current)
    const start = performance.now()
    const D = reduced() ? 0 : 800
    cancelAnimationFrame(reachRaf.current)
    const tick = (now: number) => {
      const t = D ? Math.min(1, (now - start) / D) : 1
      const k = easeOutBack(t)
      for (const g of targets.current) {
        const r0 = from.get(g.id) ?? 0
        radii.current.set(g.id, r0 + (g.r - r0) * k)
      }
      drawReach()
      if (t < 1) reachRaf.current = requestAnimationFrame(tick)
    }
    tick(start)
    return () => cancelAnimationFrame(reachRaf.current)
  }, [going, members, loaded])

  // ---- results: the middle, numbered places, and lines from everyone to the focus ----
  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return

    middle.current?.remove()
    middle.current = null
    for (const mk of places.current.values()) mk.remove()
    places.current.clear()

    if (!result) {
      ;(m.getSource('links') as GeoJSONSource).setData(empty)
      return
    }

    const mid = document.createElement('div')
    mid.className = 'mid'
    mid.innerHTML = '<i></i><span>middle</span>'
    middle.current = new Marker({ element: mid }).setLngLat(result.meeting_point).addTo(m)

    result.places.forEach((pl, i) => {
      const node = document.createElement('button')
      node.className = 'poi'
      node.style.setProperty('--i', String(i)) // staggered pop-in
      node.innerHTML = `<i><b>${KIND_EMOJI[pl.kind]}</b></i><em>${i + 1}</em><span></span>`
      node.querySelector('span')!.textContent = pl.name
      node.setAttribute('aria-label', pl.name)
      node.addEventListener('click', (e) => {
        e.stopPropagation()
        h.current.setSelected(h.current.selected === pl.id ? null : pl.id)
      })
      places.current.set(pl.id, new Marker({ element: node }).setLngLat(pl.location).addTo(m))
    })

    // frame everyone and every suggestion
    const b = new LngLatBounds()
    // whole reach circles, not just the pins, so nobody's circle is cut off
    h.current.going.forEach((p) => p.location && circle(p.location, reachMetres(p.minutes, p.mode), 16).forEach((pt) => b.extend(pt)))
    result.places.forEach((pl) => b.extend(pl.location))
    b.extend(result.meeting_point)
    // take only the zoom from cameraForBounds; pass the real centre plus padding to the flight,
    // since a pre-shifted centre gets exaggerated on a steeply tilted map
    const pad = padding(panel.current)
    const cam = m.cameraForBounds(b, { padding: pad, maxZoom: 16 })
    const to = {
      center: b.getCenter(),
      zoom: (cam?.zoom ?? m.getZoom()) - 0.25, // a touch of air: tilted views show less ground up close
      pitch: PITCH,
      bearing: m.getBearing() + 18,
      padding: pad,
    }
    if (reduced()) m.jumpTo(to)
    else m.flyTo({ ...to, duration: 1800, curve: 1.3, essential: true })
  }, [result, loaded]) // reframe only when results change, not when people move

  // ---- focus: highlight the selected place and draw everyone's line to it ----
  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return
    for (const [id, mk] of places.current) mk.getElement().classList.toggle('on', id === selected)
    if (!result) return
    const focus = result.places.find((p) => p.id === selected)
    const to = focus?.location ?? result.meeting_point
    const links = going
      .filter((p) => p.location)
      .map((p) => ({
        type: 'Feature' as const,
        properties: { color: h.current.colorOf(p.person_id) },
        geometry: { type: 'LineString' as const, coordinates: [p.location!, to] },
      }))
    ;(m.getSource('links') as GeoJSONSource).setData({ type: 'FeatureCollection', features: links })
    if (focus) {
      m.flyTo({
        center: focus.location,
        zoom: Math.max(m.getZoom(), 15.5),
        pitch: 58,
        bearing: m.getBearing() - 10,
        padding: padding(panel.current),
        duration: reduced() ? 0 : 1200,
        essential: true,
      })
    }
  }, [selected, result, going, members, loaded])

  // ---- marching ants on the lines to the meeting spot while there are results ----
  useEffect(() => {
    const m = map.current
    if (!m || !loaded || !result || reduced()) return
    let step = 0
    let last = 0
    let raf = 0
    const tick = (now: number) => {
      if (now - last > 55) {
        last = now
        step = (step + 1) % ANTS.length
        if (m.getLayer('links')) m.setPaintProperty('links', 'line-dasharray', ANTS[step])
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [result, loaded])

  // ---- placing someone: crosshair, and Escape cancels ----
  useEffect(() => {
    if (placing === null) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && h.current.setPlacing(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [placing])

  return <div ref={el} className={`map ${placing !== null ? 'placing' : ''}`} />
}
