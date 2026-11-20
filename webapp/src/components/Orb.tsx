import { useEffect, useRef } from 'react'
import { OrbEngine } from '../orb/engine'
import type { OrbState } from '../lib/types'

interface Props {
  state: OrbState
  levelRef: React.RefObject<number> // read every frame, so voice level never re-renders React
  onTap: () => void
  label: string
}

export function Orb({ state, levelRef, onTap, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const engineRef = useRef<OrbEngine | null>(null)

  useEffect(() => {
    const engine = new OrbEngine(canvasRef.current!)
    const root = document.documentElement.style
    engine.onHues = ([a, b, c]) => {
      root.setProperty('--h1', a.toFixed(1))
      root.setProperty('--h2', b.toFixed(1))
      root.setProperty('--h3', c.toFixed(1))
      engine.setLevel(levelRef.current ?? 0)
    }
    engineRef.current = engine
    return () => engine.destroy()
  }, [levelRef])

  useEffect(() => {
    engineRef.current?.setState(state)
  }, [state])

  return (
    <>
      <canvas ref={canvasRef} className="orb-canvas" aria-hidden="true" />
      <button className="talk" onClick={onTap} aria-label={label} />
    </>
  )
}
