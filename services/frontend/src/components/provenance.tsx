import type { Actor, SourceProvenance as SourceOrigin } from '@/lib/api'
import { actorLabel } from '@/lib/actors'

export function Time({ value }: { value: string }) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return <time>{value}</time>
  return (
    <time dateTime={value} title={date.toISOString()}>
      {date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
    </time>
  )
}

/**
 * Who did something, when, and why. Work by an external agent is set apart: the session
 * may be driven from another client, whose conversation is not here, so the client's name
 * and the agent's one-line note are what explain each step.
 */
export function Provenance({ actor, at, note }: { actor: Actor; at: string; note?: string }) {
  const external = actor.kind === 'external_agent'
  return (
    <div className="flex min-w-0 flex-col gap-0.5 text-xs">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-neutral-600 dark:text-neutral-400">
        {external ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 font-medium text-violet-800 dark:bg-violet-950 dark:text-violet-200">
            <span className="sr-only">External agent: </span>
            <span aria-hidden="true">↗</span>
            {actorLabel(actor)}
          </span>
        ) : (
          <span className="font-medium text-neutral-700 dark:text-neutral-300">{actorLabel(actor)}</span>
        )}
        <Time value={at} />
      </div>
      {note && (
        <p className={external ? 'text-violet-900 italic dark:text-violet-200' : 'text-neutral-600 dark:text-neutral-400'}>
          {note}
        </p>
      )}
    </div>
  )
}

/**
 * Where a data source came from: who publishes it and under what licence ("licence
 * unknown" when none was established, with the reason), the page it was found on, and
 * whether a model extracted its rows rather than the file being read as it is.
 */
export function SourceProvenance({ provenance }: { provenance: SourceOrigin }) {
  const licensed = provenance.licence && provenance.licence !== 'unknown'
  return (
    <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {provenance.publisher && <span>{provenance.publisher}</span>}
        <span className={licensed ? undefined : 'text-amber-800 dark:text-amber-300'}>
          {licensed ? provenance.licence : 'Licence unknown'}
        </span>
        {provenance.landing_page && (
          <a href={provenance.landing_page} target="_blank" rel="noreferrer" className="underline underline-offset-2">
            Landing page
          </a>
        )}
        {provenance.extracted_by_model && (
          <span className="rounded-full border px-2 py-0.5 font-medium">Model-extracted</span>
        )}
      </p>
      {provenance.found_by && (
        <p>
          Found by searching “{provenance.found_by.query}” ({provenance.found_by.scope})
        </p>
      )}
      {provenance.note && <p>{provenance.note}</p>}
    </div>
  )
}
