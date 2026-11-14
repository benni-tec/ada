import { gradeLabels, pathwaySteps, type EvidenceGrade, type ModelVersion, type PathwayStep } from '@/lib/api'

/** The pill a figure's evidence grade shows in; the national standards stand out, the
 * assumptions are marked. */
export function GradePill({ grade }: { grade: EvidenceGrade }) {
  const tone =
    grade === 'standard'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
      : grade === 'assumption'
        ? 'border-orange-200 bg-orange-50 text-orange-900 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-200'
        : grade === 'meta_analysis'
          ? 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200'
          : 'border-border bg-muted text-foreground'
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs whitespace-nowrap ${tone}`} data-grade={grade}>
      {gradeLabels[grade]}
    </span>
  )
}

const stepLabel = (step: PathwayStep | null) =>
  step === null ? 'Trigger → treatment start' : (pathwaySteps.find((s) => s.step === step)?.label ?? step)

/** What the model is built from: the criteria per country, the standard times per country
 * and their median, every parameter with its source, scale and evidence grade, the
 * toggles, the intended use and the cautions. */
export function ModelCard({ version }: { version: ModelVersion }) {
  const { spec, compiled } = version
  const stages = [
    { stage: 'suspicion', title: 'Suspicion → imaging' },
    { stage: 'well_founded', title: 'Well-founded suspicion → the pathway starts' },
  ] as const
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-base font-semibold">Intended use</h2>
        <p className="mt-1 text-sm">{spec.intended_use}</p>
        <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
          {spec.cautions.map((caution) => (
            <li key={caution}>{caution}</li>
          ))}
        </ul>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">Trigger criteria</h2>
          {stages.map(({ stage, title }) => (
            <div key={stage} className="mt-3">
              <h3 className="text-sm font-medium">{title}</h3>
              <ul className="mt-1 list-disc pl-5 text-sm">
                {spec.criteria
                  .filter((c) => c.stage === stage)
                  .map((c) => (
                    <li key={c.id}>
                      {c.text} <span className="text-muted-foreground">({c.countries.join(', ')})</span>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
          <p className="mt-3 text-xs text-muted-foreground">Finland has no national criteria.</p>
        </section>

        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">Standard times, calendar days</h2>
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-medium">Step</th>
                <th className="py-1 pr-2 font-medium">By country</th>
                <th className="py-1 font-medium">Target</th>
              </tr>
            </thead>
            <tbody>
              {spec.targets.map((t, i) => {
                const key = t.step ?? 'pathway'
                const target = compiled.targets[t.site]?.[key]?.[t.modality ?? 'any']
                return (
                  <tr key={i} className="border-t">
                    <td className="py-1 pr-2">
                      {stepLabel(t.step)}
                      {t.modality && <span className="text-muted-foreground"> · {t.modality}</span>}
                    </td>
                    <td className="py-1 pr-2 text-muted-foreground">
                      {Object.entries(t.days_by_country)
                        .map(([country, days]) => `${country} ${days}`)
                        .join(', ')}
                    </td>
                    <td className="py-1 font-semibold">{target}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted-foreground">
            The target is the median of the countries that define the step. The whole-pathway deadline is the primary one.
          </p>
        </section>
      </div>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-base font-semibold">Parameters and where they come from</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-medium">Arrow</th>
                <th className="py-1 pr-2 font-medium">Estimate</th>
                <th className="py-1 pr-2 font-medium">Source</th>
                <th className="py-1 pr-2 font-medium">Scale</th>
                <th className="py-1 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(spec.arrows).map(([arrow, name]) => {
                const p = spec.parameters[name]
                if (!p) return null
                const ci = p.ci_low != null && p.ci_high != null ? ` (${p.ci_low}–${p.ci_high})` : ''
                return (
                  <tr key={arrow} className="border-t align-top">
                    <td className="py-2 pr-2 font-medium">{arrow}</td>
                    <td className="py-2 pr-2">
                      {p.estimate}
                      {ci} <span className="text-muted-foreground">{p.form.replaceAll('_', ' ')}</span>
                    </td>
                    <td className="py-2 pr-2 text-muted-foreground">
                      {p.provenance.url ? (
                        <a href={p.provenance.url} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">
                          {p.provenance.source}
                        </a>
                      ) : (
                        p.provenance.source
                      )}
                    </td>
                    <td className="py-2 pr-2 text-muted-foreground">{p.scale.replaceAll('_', ' ')}</td>
                    <td className="py-2">
                      <GradePill grade={p.provenance.grade} />
                    </td>
                  </tr>
                )
              })}
              {spec.baseline.map((cell, i) => (
                <tr key={`baseline-${i}`} className="border-t align-top">
                  <td className="py-2 pr-2 font-medium">baseline · {cell.site} · {cell.sex}</td>
                  <td className="py-2 pr-2">{Math.round(cell.survival * 100)} of 100 alive at 5 years</td>
                  <td className="py-2 pr-2 text-muted-foreground">{cell.provenance.source}</td>
                  <td className="py-2 pr-2 text-muted-foreground">survival</td>
                  <td className="py-2">
                    <GradePill grade={cell.provenance.grade} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {compiled.warnings.length > 0 && (
          <ul className="mt-3 list-disc pl-5 text-xs text-muted-foreground">
            {compiled.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">Settings shown as a range</h2>
          <ul className="mt-2 flex flex-col gap-2 text-sm">
            {spec.toggles.map((t) => (
              <li key={t.name}>
                <span className="font-medium">{t.label}</span>{' '}
                <span className="text-muted-foreground">(default {t.default ? 'on' : 'off'})</span>: {t.about}
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-base font-semibold">Validation</h2>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            <li>Deadlines and days behind target: exact, tested against hand calculations.</li>
            <li>The average Finnish profile lands on Finland's observed survival; the residual is reported (Population).</li>
            <li className="text-orange-800 dark:text-orange-300">
              Discrimination and calibration curves: not possible, there is no patient-level data.
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}
