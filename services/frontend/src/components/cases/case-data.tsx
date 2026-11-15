import { Pencil } from 'lucide-react'
import { useState } from 'react'

import { Hint } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { fieldLabel, type CaseEvent, type CaseState, type CaseType, type CaseValues, type Field } from '@/lib/api'
import { cleanValues, day, displayValue, stepLabel } from '@/lib/cases'

import { FieldControls } from './fields'

/**
 * The case's values beside its step timeline, edited in place: the pencil turns the values
 * into the schema's controls; saving makes a new revision and runs the automatic models.
 */
export function CaseData({
  caseType,
  state,
  own,
  clockStart,
  onSave,
  saving,
  error,
}: {
  caseType: CaseType
  state: CaseState
  /** The case type's own fields: no model reads them. */
  own: ReadonlySet<string>
  /** The day the pathway clock started, from the latest pathway result. */
  clockStart: number | null
  onSave: (values: CaseValues) => Promise<unknown>
  saving: boolean
  error: unknown
}) {
  const [draft, setDraft] = useState<CaseValues | null>(null)
  const editing = draft !== null
  const values = state.case.values
  const dayMaps = caseType.fields.filter((f) => f.type === 'day_map')
  const shown = caseType.fields.filter((f) => f.type !== 'day_map')

  return (
    <section className="rounded-xl border bg-card" aria-labelledby="case-data-title">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <h2 id="case-data-title" className="font-semibold">
          Case data
        </h2>
        {!editing && (
          <Hint label="Edit">
            <Button variant="outline" size="icon-sm" aria-label="Edit the case data" onClick={() => setDraft({ ...values })}>
              <Pencil />
            </Button>
          </Hint>
        )}
      </header>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void onSave(cleanValues(draft)).then(() => setDraft(null), () => undefined)
          }}
        >
          <div className="p-4">
            <FieldControls fields={caseType.fields} values={draft} onChange={setDraft} />
          </div>
          {error != null && (
            <div className="px-4 pb-3">
              <ErrorNotice error={error} prefix="Not saved:" />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t px-4 py-3">
            <span className="mr-auto text-xs text-muted-foreground">
              Saving makes revision {state.case.revision + 1} and runs the automatic models again.
            </span>
            <Button type="button" variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      ) : (
        <div className="grid min-[860px]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <dl className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] content-start gap-x-5 gap-y-3.5 p-4">
            {shown.map((field) => (
              <div key={field.name} data-own={own.has(field.name) || undefined}>
                <dt className="text-xs text-muted-foreground">
                  {fieldLabel(field)}
                  {own.has(field.name) && <span className="text-blue-700 dark:text-blue-400"> · case type field</span>}
                </dt>
                <dd className="mt-0.5 font-medium break-words">{displayValue(field, values[field.name])}</dd>
              </div>
            ))}
          </dl>
          {dayMaps.length > 0 && (
            <div className="border-t p-4 min-[860px]:border-t-0 min-[860px]:border-l">
              {dayMaps.map((field) => (
                <Timeline
                  key={field.name}
                  field={field}
                  days={(values[field.name] as Record<string, number> | undefined) ?? {}}
                  events={state.events.filter((e) => e.field === field.name)}
                  treatmentStarted={values.treatment_started === true}
                  clockStart={clockStart}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

// Where each pathway step ends, as the timeline names it.
const endpoints: Record<string, string> = {
  contact_to_physician: 'Physician',
  physician_to_imaging: 'Imaging done',
  imaging_to_referral: 'Pathway referral',
  referral_to_specialist: 'First specialist visit',
  specialist_to_workup: 'Work-up complete',
  workup_to_treatment: 'Treatment start',
}

type Row = { day: number; text: string; note?: string; recorded?: string; kind?: 'clock' | 'open' }

/** The steps of a day-map field as days from the first contact. The last step given is the
 * current one, unless treatment has started. */
function Timeline({
  field,
  days,
  events,
  treatmentStarted,
  clockStart,
}: {
  field: Field
  days: Record<string, number>
  events: CaseEvent[]
  treatmentStarted: boolean
  clockStart: number | null
}) {
  const given = field.levels.filter((level) => days[level] != null)
  const recorded = (step: string) => {
    const last = events.filter((e) => e.field === field.name && e.level === step).sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))[0]
    return last ? day(last.recorded_at) : undefined
  }
  const done = treatmentStarted && given.includes('workup_to_treatment')
  const current = done ? undefined : given.at(-1)
  const rows: Row[] = []
  // The pathway counts its days from the first contact; the symptoms come before it.
  if (given.length > 0 && field.levels.includes('symptoms_to_contact')) {
    const symptoms = days.symptoms_to_contact
    rows.push({
      day: 0,
      text: 'First contact',
      note: symptoms != null ? `${symptoms} days of symptoms before` : undefined,
      recorded: recorded('symptoms_to_contact'),
    })
  }
  let at = 0
  for (const level of given) {
    if (level === 'symptoms_to_contact') continue
    at += days[level]
    const name = endpoints[level] ?? stepLabel(level)
    if (level === current) {
      rows.push({ day: at, text: `Today · no ${name.toLowerCase()} yet`, note: `${days[level]} days so far`, recorded: recorded(level), kind: 'open' })
    } else {
      rows.push({ day: at, text: name, recorded: recorded(level), kind: clockStart === at ? 'clock' : undefined })
    }
  }

  return (
    <div>
      <h3 className="mb-2.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">{field.label || 'Steps'}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No steps yet.</p>
      ) : (
        <ol className="text-sm" aria-label="Steps">
          {rows.map((row, i) => (
            <li
              key={i}
              data-kind={row.kind}
              className="relative ml-[5px] grid grid-cols-[52px_minmax(0,1fr)_auto] gap-2 border-l-2 pb-2.5 pl-3.5 last:pb-0"
            >
              <span
                aria-hidden="true"
                className={`absolute top-[5px] -left-[6px] size-2.5 rounded-full border-2 ${
                  row.kind === 'clock' ? 'border-foreground bg-foreground' : row.kind === 'open' ? 'border-dashed border-orange-700 bg-background' : 'border-foreground bg-background'
                }`}
              />
              <span className="text-muted-foreground tabular-nums">day {row.day}</span>
              <span>
                {row.text}
                {row.kind === 'clock' && <strong>: clock starts</strong>}
                {row.note && <span className="text-xs text-muted-foreground"> · {row.note}</span>}
              </span>
              <span className="text-xs text-muted-foreground">{row.recorded}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
