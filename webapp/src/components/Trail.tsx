import type { TrailStep } from '../lib/types'

/** Plain-language progress while Tab works: one short line per step, newest brightest. */
export function Progress({ steps, running }: { steps: TrailStep[]; running: boolean }) {
  return (
    <ol className="progress" aria-label="What Tab is doing">
      {steps.map((s, i) => (
        <li key={s.step + i} className={i === steps.length - 1 ? 'latest' : ''}>
          <i className="tick" aria-hidden="true" />
          {s.say}
        </li>
      ))}
      {running && (
        <li className="pending" aria-hidden="true">
          <i />
          <i />
          <i />
        </li>
      )}
    </ol>
  )
}

/** The technical steps, for anyone curious how Tab got there. */
export function HowSteps({ steps }: { steps: TrailStep[] }) {
  const total = steps.reduce((t, s) => t + s.ms, 0)
  return (
    <ol className="how">
      {steps.map((s, i) => (
        <li key={s.step + i}>
          <span className="how-step">{s.step}</span>
          <span className="how-detail">{s.detail}</span>
          <span className="how-model">{s.model ?? 'python'}</span>
          <span className="how-ms">{s.ms}ms</span>
        </li>
      ))}
      <li className="how-total">
        <span>{steps.length} steps</span>
        <span>{(total / 1000).toFixed(2)}s</span>
      </li>
    </ol>
  )
}
