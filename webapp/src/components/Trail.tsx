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

