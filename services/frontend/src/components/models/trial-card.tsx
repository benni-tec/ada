import type { TrialVersion } from '@/lib/api'

/** What a trial matcher is: its intended use and cautions, how it matches a case, and the
 * data steps it reads whenever it runs (so there is no list of trials to pin here: the
 * national picture is on the trials dashboards). */
export function TrialCard({ version }: { version: TrialVersion }) {
  const { spec } = version
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-base font-semibold">Intended use</h2>
        <p className="mt-1 text-sm">{spec.intended_use}</p>
        <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
          {(spec.cautions ?? []).map((caution) => (
            <li key={caution}>{caution}</li>
          ))}
        </ul>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">How a case is matched</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">
            <li>
              The case's site against the trial's cancer groups:{' '}
              {Object.entries(spec.groups ?? {})
                .map(([site, group]) => `${site} → ${group}`)
                .join(', ')}
              . This is the only filter.
            </li>
            <li>Sex and age limits are shown beside each trial, never used to leave one out.</li>
            <li>Sorted by distance to the nearest recruiting Nordic site, from the city the county step names for the case's county (Helsinki without one).</li>
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">The eligibility text is shown as the registry wrote it and never judged.</p>
        </section>
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">What it reads</h2>
          <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Trials</dt>
            <dd className="font-mono text-xs break-all">{spec.operator_id}</dd>
            <dt className="text-muted-foreground">County cities</dt>
            <dd className="font-mono text-xs break-all">{spec.county_operator_id ?? '–'}</dd>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground">
            Both are read whenever the matcher runs, so a result is as current as the data; each result records the runs it read. ClinicalTrials.gov, recruiting sites in Finland, Sweden, Norway and Denmark (docs/trials.md).
          </p>
        </section>
      </div>
    </div>
  )
}
