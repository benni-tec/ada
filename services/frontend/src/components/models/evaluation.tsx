import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  errorMessage,
  evaluateModel,
  pathwaySteps,
  type Deadline,
  type Evaluation,
  type EvaluationInputs,
  type Id,
  type ModelVersion,
  type PathwayStep,
} from '@/lib/api'

import { GradePill } from './model-card'

const selectClass = 'h-9 rounded-md border bg-background px-2 text-sm'

/** The evaluation of one synthetic profile: the form on the left, and on the right, in
 * this order, the trigger and the deadlines (exact), the days behind target, the survival
 * figures per setting (second, graded), the support to offer and the cautions. The form's
 * state lives here only, never in the URL. */
export function EvaluationTab({ modelId, version }: { modelId: Id; version: ModelVersion }) {
  const { spec } = version
  const level = (term: string) => spec.terms.find((t) => t.name === term)
  const [inputs, setInputs] = useState<EvaluationInputs>({
    site: spec.sites[0],
    sex: level('sex')?.reference ?? 'female',
    age_band: level('age_band')?.reference ?? null,
    education: level('education')?.reference ?? null,
    route: level('route')?.reference ?? null,
    stage: null,
    intent: 'unknown',
    modality: 'surgery',
    presentation: [],
    days: {},
    treatment_started: false,
    toggles: {},
  })
  const evaluate = useMutation({ mutationFn: (body: EvaluationInputs) => evaluateModel(modelId, body) })
  const set = (patch: Partial<EvaluationInputs>) => setInputs((current) => ({ ...current, ...patch }))
  const setDay = (step: PathwayStep, value: string) =>
    setInputs((current) => {
      const days = { ...current.days }
      if (value === '') delete days[step]
      else days[step] = Math.max(0, Number(value))
      return { ...current, days }
    })
  const togglePresentation = (id: string) =>
    setInputs((current) => ({
      ...current,
      presentation: current.presentation?.includes(id)
        ? current.presentation.filter((x) => x !== id)
        : [...(current.presentation ?? []), id],
    }))
  const criteria = spec.criteria.filter((c) => c.site === inputs.site)

  return (
    <div className="flex flex-wrap items-start gap-6">
      <form
        className="flex w-full flex-col gap-4 rounded-lg border bg-card p-4 lg:w-80"
        onSubmit={(event) => {
          event.preventDefault()
          evaluate.mutate(inputs)
        }}
      >
        <div>
          <h2 className="text-base font-semibold">Example profile</h2>
          <p className="text-xs text-muted-foreground">Synthetic profiles only.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Select label="Cancer site" value={inputs.site} options={spec.sites} onChange={(site) => set({ site })} />
          {spec.terms
            .filter((t) => t.display === 'patient' || t.name === 'education')
            .map((t) => (
              <Select
                key={t.name}
                label={t.name.replaceAll('_', ' ')}
                value={(inputs[t.name as keyof EvaluationInputs] as string | null) ?? ''}
                options={t.name === 'stage' ? ['', ...t.levels] : t.levels}
                onChange={(value) => set({ [t.name]: value === '' ? null : value })}
              />
            ))}
          <Select label="Intent" value={inputs.intent ?? 'unknown'} options={['unknown', 'curative', 'palliative']} onChange={(intent) => set({ intent: intent as EvaluationInputs['intent'] })} />
          <Select label="Treatment" value={inputs.modality ?? 'surgery'} options={['surgery', 'radiotherapy', 'drugs']} onChange={(modality) => set({ modality: modality as EvaluationInputs['modality'] })} />
        </div>
        {(['suspicion', 'well_founded'] as const).map((stage) => (
          <fieldset key={stage} className="flex flex-col gap-1.5">
            <legend className="mb-1 text-sm font-semibold">
              {stage === 'suspicion' ? 'Presentation at first contact' : 'Findings so far'}
            </legend>
            {criteria
              .filter((c) => c.stage === stage)
              .map((c) => (
                <label key={c.id} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={inputs.presentation?.includes(c.id) ?? false}
                    onChange={() => togglePresentation(c.id)}
                  />
                  {c.text}
                </label>
              ))}
          </fieldset>
        ))}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 text-sm font-semibold">Days in each step so far</legend>
          {pathwaySteps.map(({ step, label }, i) => (
            <label key={step} className="grid grid-cols-[minmax(0,1fr)_72px] items-center gap-2 text-sm text-muted-foreground">
              {i + 1} · {label}
              <input
                type="number"
                min={0}
                className="h-8 rounded-md border bg-background px-2 text-right text-foreground"
                value={inputs.days?.[step] ?? ''}
                placeholder="–"
                aria-label={`Days in step ${i + 1}`}
                onChange={(event) => setDay(step, event.target.value)}
              />
            </label>
          ))}
        </fieldset>
        <Button type="submit" disabled={evaluate.isPending}>
          Evaluate
        </Button>
        {evaluate.isError && <p className="text-sm text-destructive">{errorMessage(evaluate.error)}</p>}
      </form>

      <div className="flex min-w-0 flex-1 basis-[520px] flex-col gap-6">
        {evaluate.data ? (
          <Result result={evaluate.data} version={version} inputs={inputs} onToggle={(name, on) => {
            const next = { ...inputs, toggles: { ...inputs.toggles, [name]: on } }
            setInputs(next)
            evaluate.mutate(next)
          }} />
        ) : (
          <p className="text-sm text-muted-foreground">Fill in the profile and evaluate.</p>
        )}
      </div>
    </div>
  )
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: readonly string[]; onChange: (value: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium capitalize">
      {label}
      <select className={selectClass} value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o === '' ? 'Not known yet' : o.replaceAll('_', ' ')}
          </option>
        ))}
      </select>
    </label>
  )
}

const statusWords: Record<Deadline['status'], (by: number) => string> = {
  met: (by) => (by === 0 ? 'met on the day' : `met, ${by} days early`),
  late: (by) => `late by ${by} day${by === 1 ? '' : 's'}`,
  due: (by) => (by === 0 ? 'due today' : `due in ${by} day${by === 1 ? '' : 's'}`),
  overdue: (by) => `overdue by ${by} day${by === 1 ? '' : 's'}`,
  not_applicable: () => 'no standard time',
}

function Result({ result, version, inputs, onToggle }: { result: Evaluation; version: ModelVersion; inputs: EvaluationInputs; onToggle: (name: string, on: boolean) => void }) {
  const { trigger, deadlines, pathway, survival, levers, flags, warnings } = result
  const next = deadlines.find((d) => d.status === 'overdue') ?? deadlines.find((d) => d.status === 'due')
  const max = 60
  return (
    <>
      <section className="rounded-lg border border-foreground bg-card p-4" data-section="trigger">
        <h2 className="text-base font-semibold">Fast-track pathway</h2>
        <p className="mt-1">{trigger.note}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {[trigger.suspicion, trigger.well_founded].map((stage) => (
            <div key={stage.stage} className="rounded-md border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <strong>{stage.stage === 'suspicion' ? 'Suspicion, at first contact' : 'Well-founded suspicion'}</strong>
                <span className="rounded-full border bg-muted px-2 text-xs">{stage.fired ? stage.countries.join(' · ') : 'not met'}</span>
              </div>
              {stage.criteria.length > 0 && <p className="mt-1 text-muted-foreground">{stage.criteria.join('; ')}</p>}
            </div>
          ))}
        </div>
        <ul className="mt-3 flex flex-col gap-2">
          {deadlines.map((d) => {
            const urgent = d.status === 'due' || d.status === 'overdue'
            return (
              <li key={d.label} className={`grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-md px-3 py-2 text-sm ${urgent ? 'bg-orange-50 dark:bg-orange-950' : 'bg-muted/50'}`}>
                <span>
                  <span className="font-medium">{d.label}</span>
                  <span className="block text-xs text-muted-foreground">
                    {d.rule}
                    {d.countries.length > 0 && ` · ${d.countries.join(', ')}`}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">{d.due_day != null ? `due day ${d.due_day}` : ''}</span>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${urgent ? 'bg-orange-700 text-white' : 'bg-muted'}`} data-status={d.status}>
                  {statusWords[d.status](d.by)}
                </span>
              </li>
            )
          })}
        </ul>
        {next && (
          <p className="mt-3 rounded-md bg-foreground px-3 py-2 text-sm text-background">
            <strong>Next:</strong> {next.label.toLowerCase()}, {statusWords[next.status](next.by)} under the Nordic standard.
          </p>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4" data-section="pathway">
        <h2 className="text-base font-semibold">Where the days go</h2>
        <p className="mt-1">
          This pathway is <strong className="text-orange-700 dark:text-orange-400">{result.days_behind} days behind target</strong> so far.
        </p>
        <div className="mt-3 flex flex-col gap-2">
          {pathway.map((row) => (
            <div key={row.step} className="grid grid-cols-[minmax(130px,220px)_minmax(0,1fr)_110px] items-center gap-3 text-sm">
              <span>
                {row.label}
                <span className="block text-xs text-muted-foreground">
                  {row.patient_interval ? 'before first contact' : row.current ? 'current step, so far' : row.days == null ? 'not started' : 'done'}
                </span>
              </span>
              <div className="relative h-4 rounded bg-muted">
                {row.days != null && (
                  <div className={`absolute inset-y-0 left-0 rounded-l ${row.patient_interval ? 'bg-neutral-400' : 'bg-neutral-700'}`} style={{ width: `${Math.min(100, (Math.min(row.days, row.target ?? row.days) / max) * 100)}%` }} />
                )}
                {row.gap > 0 && row.target != null && (
                  <div className="absolute inset-y-0 rounded-r bg-orange-700" style={{ left: `${Math.min(100, (row.target / max) * 100)}%`, width: `${Math.min(100, (row.gap / max) * 100)}%` }} />
                )}
                {row.target != null && <div className="absolute -inset-y-1 w-0.5 bg-blue-700" style={{ left: `${Math.min(100, (row.target / max) * 100)}%` }} />}
              </div>
              <span className="text-right text-xs">
                <span className={`block text-sm font-semibold ${row.gap > 0 ? 'text-orange-700 dark:text-orange-400' : ''}`}>
                  {row.days == null ? '–' : `${row.days} d${row.gap > 0 ? ` (+${row.gap})` : ''}`}
                </span>
                <span className="text-muted-foreground">{row.target == null ? 'no target' : `target ${row.target} d`}</span>
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border bg-card p-4" data-section="survival">
        <h2 className="text-base font-semibold">Alive at 5 years, out of 100 people with this profile</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Nordic survival for this profile, adjusted for the days beyond target. The evidence for these figures is weaker
          than for the deadlines above.
        </p>
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Settings">
          {version.spec.toggles.map((t) => {
            const on = survival.setting[t.name] ?? t.default
            return (
              <button key={t.name} type="button" aria-pressed={on} onClick={() => onToggle(t.name, !on)} className={`rounded-full border px-3 py-1.5 text-sm ${on ? 'border-foreground bg-foreground text-background' : 'bg-background'}`}>
                {t.label}
              </button>
            )
          })}
        </div>
        <div className="mt-4 flex flex-wrap gap-8">
          <IconArray value={survival.now} extra={0} label="as it stands" />
          <IconArray value={survival.now} extra={survival.on_target - survival.now} label="if the remaining steps are on target" total={survival.on_target} />
          <div className="min-w-[200px] flex-1 rounded-md bg-muted p-3 text-sm">
            <strong>Range across the settings</strong>
            <br />
            As it stands: {survival.range_now.low}–{survival.range_now.high} of 100
            <br />
            On target: {survival.range_on_target.low}–{survival.range_on_target.high} of 100
          </div>
        </div>
        {levers.length > 0 && (
          <ol className="mt-4 flex flex-col gap-2">
            {levers.map((lever) => (
              <li key={lever.step + lever.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-md border p-3 text-sm">
                <span>
                  <strong>{lever.label}</strong>
                  {lever.gain > 0 && <span> · about {lever.gain} more of 100</span>}
                  <span className="block text-muted-foreground">{lever.text}</span>
                </span>
                <GradePill grade={lever.grade} />
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4" data-section="support">
          <h2 className="text-base font-semibold">Support to offer</h2>
          {flags.length > 0 ? (
            <ul className="mt-2 list-disc pl-5 text-sm">
              {flags.map((flag) => (
                <li key={flag}>{flag}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">Nothing flagged for this profile.</p>
          )}
          {inputs.education && <p className="mt-2 text-xs text-muted-foreground">Education is not used to lower the survival figures.</p>}
        </section>
        <section className="rounded-lg border bg-card p-4" data-section="cautions">
          <h2 className="text-base font-semibold">Read with care</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
      </div>
    </>
  )
}

function IconArray({ value, extra, label, total }: { value: number; extra: number; label: string; total?: number }) {
  const shown = total ?? value
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className={`text-3xl font-bold ${total != null ? 'text-blue-700 dark:text-blue-400' : ''}`}>{shown}</span>
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>
      <div role="img" aria-label={`${shown} of 100 people alive at 5 years ${label}`} className="grid grid-cols-10 gap-1">
        {Array.from({ length: 100 }, (_, i) => (
          <span key={i} className={`size-3 rounded-full ${i < value ? 'bg-neutral-700' : i < value + extra ? 'bg-blue-700' : 'bg-muted'}`} />
        ))}
      </div>
    </div>
  )
}
