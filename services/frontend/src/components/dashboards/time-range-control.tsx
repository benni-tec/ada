import { useId, useState, type FormEvent } from 'react'

import type { DashboardTimeRange } from '@/lib/api'

import { describeRange, yearOf, yearsToRange } from './ranges'

const inputClass =
  'w-24 rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900'
const buttonClass =
  'rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium disabled:opacity-50 dark:border-neutral-700'

/**
 * The range the dashboard is viewed at, by year. "Show" starts a new run for it; the
 * widgets then all read that run. "Save as default" makes it the range the dashboard
 * opens with for everyone.
 */
export function TimeRangeControl({
  range,
  isDefault,
  onShow,
  onSaveDefault,
  saving,
}: {
  range: DashboardTimeRange
  /** Whether `range` is the dashboard's saved default. */
  isDefault: boolean
  onShow: (range: DashboardTimeRange) => void
  onSaveDefault: (range: DashboardTimeRange) => void
  saving: boolean
}) {
  const fromId = useId()
  const toId = useId()
  const [from, setFrom] = useState(yearOf(range.start))
  const [to, setTo] = useState(yearOf(range.end))
  const invalid = from !== '' && to !== '' && Number(from) > Number(to)
  const edited = yearsToRange(from, to)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!invalid) onShow(edited)
  }

  return (
    <form onSubmit={submit} aria-label="Time range" className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={fromId} className="text-xs font-medium">
          From year
        </label>
        <input
          id={fromId}
          type="number"
          inputMode="numeric"
          min={1900}
          max={2100}
          value={from}
          placeholder="any"
          onChange={(event) => setFrom(event.target.value)}
          className={inputClass}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={toId} className="text-xs font-medium">
          To year
        </label>
        <input
          id={toId}
          type="number"
          inputMode="numeric"
          min={1900}
          max={2100}
          value={to}
          placeholder="any"
          onChange={(event) => setTo(event.target.value)}
          className={inputClass}
        />
      </div>
      <button
        type="submit"
        disabled={invalid}
        className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
      >
        Show
      </button>
      <button
        type="button"
        disabled={invalid || saving || (isDefault && describeRange(edited) === describeRange(range))}
        onClick={() => onSaveDefault(edited)}
        className={buttonClass}
      >
        {saving ? 'Saving…' : 'Save as default'}
      </button>
      {invalid && (
        <p role="alert" className="basis-full text-sm text-red-700 dark:text-red-400">
          The last year is before the first.
        </p>
      )}
    </form>
  )
}
