import { useId } from 'react'

import { Input } from '@/components/ui/input'
import { fieldLabel, levelLabel, type CaseValues, type Field } from '@/lib/api'
import { stepLabel } from '@/lib/cases'

// The controls a case type's schema generates: one per field, by its type. The same
// controls make the new-case form and the data card's edit mode.

const selectClass =
  'h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30'

/** Every field of the schema as a control, in a grid. */
export function FieldControls({
  fields,
  values,
  onChange,
  wide = [],
}: {
  fields: readonly Field[]
  values: CaseValues
  onChange: (values: CaseValues) => void
  /** Fields (by name) that take the whole row. */
  wide?: readonly string[]
}) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-5 gap-y-4">
      {fields.map((field) => (
        <div
          key={field.name}
          className={field.type === 'enum_list' || field.type === 'day_map' || wide.includes(field.name) ? 'col-span-full' : ''}
        >
          <FieldControl field={field} value={values[field.name]} onChange={(value) => onChange({ ...values, [field.name]: value })} />
        </div>
      ))}
    </div>
  )
}

/** One field: its label, its control, and its help below. */
export function FieldControl({ field, value, onChange }: { field: Field; value: unknown; onChange: (value: unknown) => void }) {
  const id = useId()
  const helpId = `${id}-help`
  const label = fieldLabel(field)
  const help = field.help ? (
    <p id={helpId} className="text-xs text-muted-foreground">
      {field.help}
    </p>
  ) : null
  const describedBy = field.help ? helpId : undefined
  const required = field.required ? <span className="text-muted-foreground"> · required</span> : null

  if (field.type === 'enum_list') {
    const chosen = Array.isArray(value) ? (value as string[]) : []
    return (
      <fieldset className="flex flex-col gap-1.5" aria-describedby={describedBy}>
        <legend className="mb-1 text-xs font-medium text-muted-foreground">
          {label}
          {required}
        </legend>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-4 gap-y-1">
          {field.levels.map((level) => (
            <label key={level} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={chosen.includes(level)}
                onChange={() => onChange(chosen.includes(level) ? chosen.filter((x) => x !== level) : [...chosen, level])}
              />
              {levelLabel(level)}
            </label>
          ))}
        </div>
        {help}
      </fieldset>
    )
  }

  if (field.type === 'day_map') {
    const days = value && typeof value === 'object' ? (value as Record<string, number>) : {}
    const setDay = (level: string, text: string) => {
      const next = { ...days }
      if (text === '') delete next[level]
      else next[level] = Math.max(0, Math.round(Number(text)))
      onChange(next)
    }
    return (
      <fieldset className="flex flex-col gap-1.5" aria-describedby={describedBy}>
        <legend className="mb-1 text-xs font-medium text-muted-foreground">
          {label}
          {required}
        </legend>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-x-5 gap-y-1.5">
          {field.levels.map((level) => (
            <label key={level} className="grid grid-cols-[minmax(0,1fr)_76px] items-center gap-2 text-sm">
              {stepLabel(level)}
              <Input
                type="number"
                min={0}
                step={1}
                className="text-right"
                placeholder="–"
                value={days[level] ?? ''}
                onChange={(event) => setDay(level, event.target.value)}
              />
            </label>
          ))}
        </div>
        {help}
      </fieldset>
    )
  }

  if (field.type === 'boolean') {
    return (
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 pt-5 text-sm">
          <input type="checkbox" checked={value === true} aria-describedby={describedBy} onChange={(event) => onChange(event.target.checked)} />
          {label}
        </label>
        {help}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
        {required}
      </label>
      {field.type === 'enum' ? (
        <select
          id={id}
          className={selectClass}
          required={field.required}
          aria-describedby={describedBy}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value === '' ? undefined : event.target.value)}
        >
          <option value="">{field.required ? 'Choose…' : 'Not known yet'}</option>
          {field.levels.map((level) => (
            <option key={level} value={level}>
              {levelLabel(level)}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={id}
          type={field.type === 'text' ? 'text' : field.type === 'date' ? 'date' : 'number'}
          step={field.type === 'integer' ? 1 : field.type === 'number' ? 'any' : undefined}
          required={field.required}
          aria-describedby={describedBy}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(event) => {
            const text = event.target.value
            if (text === '') onChange(undefined)
            else if (field.type === 'number' || field.type === 'integer') onChange(Number(text))
            else onChange(text)
          }}
        />
      )}
      {help}
    </div>
  )
}
