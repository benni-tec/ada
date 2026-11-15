import { useQuery } from '@tanstack/react-query'

import { ErrorNotice, Loading } from '@/components/notices'
import { pathwaySteps, populationQuery, type Id, type PathwayVersion } from '@/lib/api'

/** How much of the comparison country's survival shortfall waiting times can explain: per
 * site and sex, the baseline, the baseline with that country's extra days, and its
 * observed survival, all 5-year relative survival per 100. What is left is not timing. */
export function PopulationTab({ modelId, version }: { modelId: Id; version: PathwayVersion }) {
  const { data: figures, error } = useQuery(populationQuery(modelId))
  const comparison = version.spec.comparison
  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Start from the Nordic level, add {comparison.country}'s extra days at the published rate, and compare with{' '}
        {comparison.country}'s observed survival. What is left is not timing. All figures are 5-year relative survival per
        100: survival compared with people of the same age and sex without cancer.
      </p>
      {error ? (
        <ErrorNotice error={error} prefix="Could not load the population figures:" />
      ) : !figures ? (
        <Loading what="the population figures" />
      ) : figures.length === 0 ? (
        <p className="text-sm text-muted-foreground">No population figures for this model.</p>
      ) : null}
      {figures?.map((f) => {
        const explained = f.baseline - f.timing_adjusted
        const left = f.timing_adjusted - f.observed
        const bars = [
          { label: 'Nordic level', value: f.baseline, tone: 'bg-blue-700' },
          { label: `With ${comparison.country}'s waits`, value: f.timing_adjusted, tone: 'bg-neutral-700' },
          { label: `${comparison.country}, observed`, value: f.observed, tone: 'bg-orange-700' },
        ]
        return (
          <section key={`${f.site}-${f.sex}`} className="rounded-lg border bg-card p-4" data-population={`${f.site}:${f.sex}`}>
            <h2 className="text-base font-semibold">
              <span className="capitalize">{f.site}</span> cancer, {f.sex}: 5-year relative survival per 100
            </h2>
            <div className="mt-3 flex flex-col gap-2">
              {bars.map((b) => (
                <div key={b.label} className="grid grid-cols-[minmax(140px,220px)_minmax(0,1fr)_48px] items-center gap-3 text-sm">
                  <span>{b.label}</span>
                  <div className="h-6 rounded bg-muted">
                    <div className={`h-6 rounded ${b.tone}`} style={{ width: `${Math.min(100, b.value)}%` }} />
                  </div>
                  <span className="text-right text-lg font-bold">{b.value}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded-md bg-muted p-3">
                <strong>Explained by timing: {explained} per 100</strong>
                <p className="mt-1 text-muted-foreground">{f.note}</p>
              </div>
              <div className="rounded-md border border-orange-200 bg-orange-50 p-3 dark:border-orange-900 dark:bg-orange-950">
                <strong>Not explained: {left} per 100</strong>
                <p className="mt-1 text-muted-foreground">
                  The residual (factor {f.residual.toFixed(2)} on the excess hazard). On by default on the evaluation
                  page, so a profile's figures match {comparison.country}'s survival.
                </p>
              </div>
            </div>
          </section>
        )
      })}
      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-base font-semibold">Where the days go in {comparison.country}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Typical days per step. The steps before the trigger are system levers: appointment access, nurse-ordered
          imaging, direct CT from primary care.
        </p>
        {Object.entries(comparison.days).map(([site, days]) => (
          <table key={site} className="mt-3 w-full text-sm" data-site={site}>
            <caption className="py-1 text-left font-medium">
              <span className="capitalize">{site}</span> cancer
            </caption>
            <tbody>
              {pathwaySteps.map(({ step, label }) => (
                <tr key={step} className="border-t">
                  <td className="py-1 pr-2">{label}</td>
                  <td className="py-1 text-right font-medium">{days[step] ?? '–'} d</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
        <p className="mt-2 text-xs text-muted-foreground">{comparison.provenance.source}</p>
      </section>
    </div>
  )
}
