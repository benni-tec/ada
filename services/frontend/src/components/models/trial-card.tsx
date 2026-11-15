import type { TrialVersion } from '@/lib/api'

const cityLabels: Record<string, string> = { helsinki: 'Helsinki', kuopio: 'Kuopio', oulu: 'Oulu' }

const ages = (min?: number | null, max?: number | null) =>
  min == null && max == null ? 'any age' : `${min ?? 0}–${max == null ? '' : max}`

/** What a trial matcher is built from: its intended use and cautions, the data step it read
 * and when, how it matches, and the trials this version pinned. */
export function TrialCard({ version }: { version: TrialVersion }) {
  const { spec, compiled } = version
  const read = new Date(compiled.read_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
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
            <li>The case's site against the trial's cancer groups: {Object.entries(spec.groups ?? {}).map(([site, group]) => `${site} → ${group}`).join(', ')}.</li>
            <li>Sex against the trial's sex (all, female or male).</li>
            <li>The age group against the trial's age limits; a group only partly inside is marked uncertain.</li>
            <li>Trials with a Finnish site first, then the nearest recruiting Nordic site from the city nearest the case's county (Helsinki, Kuopio or Oulu).</li>
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">The eligibility text is shown as the registry wrote it and never judged.</p>
        </section>
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">Where the trials come from</h2>
          <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Data step</dt>
            <dd className="font-mono text-xs break-all">{spec.operator_id}</dd>
            <dt className="text-muted-foreground">Read</dt>
            <dd>{read}{compiled.run_id ? <span className="text-muted-foreground"> · run <span className="font-mono text-xs">{compiled.run_id}</span></span> : null}</dd>
            <dt className="text-muted-foreground">Trials pinned</dt>
            <dd>{compiled.trials.length}</dd>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground">ClinicalTrials.gov, recruiting sites in Finland, Sweden, Norway and Denmark (docs/trials.md). A new version reads them again.</p>
        </section>
      </div>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-base font-semibold">Pinned trials</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-medium">Trial</th>
                <th className="py-1 pr-2 font-medium">Groups</th>
                <th className="py-1 pr-2 font-medium">Sex · ages</th>
                <th className="py-1 pr-2 font-medium">Recruiting in</th>
                <th className="py-1 font-medium">Nearest to Helsinki</th>
              </tr>
            </thead>
            <tbody>
              {compiled.trials.map((t) => {
                const near = t.nearest?.helsinki
                return (
                  <tr key={t.nct_id} className="border-t align-top">
                    <td className="py-2 pr-2">
                      <a href={t.url} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">
                        {t.title}
                      </a>
                      <div className="text-xs text-muted-foreground">{t.nct_id}{t.phase ? ` · ${t.phase}` : ''}</div>
                    </td>
                    <td className="py-2 pr-2">{(t.cancer_groups ?? []).join(', ')}</td>
                    <td className="py-2 pr-2 whitespace-nowrap">{(t.sex ?? 'ALL').toLowerCase()} · {ages(t.min_age_years, t.max_age_years)}</td>
                    <td className="py-2 pr-2">{(t.recruiting_countries ?? []).join(', ')}</td>
                    <td className="py-2">{near ? `${near.city ?? near.country}${near.km != null ? `, ${Math.round(near.km)} km` : ''}` : '–'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Distances are great-circle kilometres from {Object.values(cityLabels).join(', ')}; no travel time is claimed.</p>
      </section>
    </div>
  )
}
