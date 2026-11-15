// How the case pages put values, times and results into words.

import { levelLabel, pathwaySteps, type CaseResult, type CaseValues, type Field } from '@/lib/api'

/** "15 Nov, 10:42" */
export function when(at: string) {
  const date = new Date(at)
  return `${date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}, ${date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
}

/** "15 Nov" */
export function day(at: string) {
  return new Date(at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** How a result came about: "Automatically" or "On request". */
export const triggerLabel = (result: CaseResult) => (result.trigger === 'auto' ? 'Automatically' : 'On request')

const stepLabels = new Map<string, string>(pathwaySteps.map(({ step, label }) => [step, label]))

/** A day-map level's words: the pathway's step names where they apply. */
export const stepLabel = (level: string) => stepLabels.get(level) ?? levelLabel(level)

/** A value as the pages show it. */
export function displayValue(field: Field, value: unknown): string {
  if (value === null || value === undefined || value === '') return '–'
  switch (field.type) {
    case 'boolean':
      return value ? 'Yes' : 'No'
    case 'enum':
      return levelLabel(String(value))
    case 'enum_list':
      return Array.isArray(value) && value.length > 0 ? value.map((v) => levelLabel(String(v))).join(' · ') : '–'
    case 'day_map': {
      const days = Object.entries(value as Record<string, number>)
      return days.length > 0 ? days.map(([step, n]) => `${stepLabel(step)}: ${n} d`).join(' · ') : '–'
    }
    default:
      return String(value)
  }
}

/** The values without the ones left empty, as the API takes them. */
export function cleanValues(values: CaseValues): CaseValues {
  return Object.fromEntries(
    Object.entries(values).filter(([, v]) => {
      if (v === undefined || v === null || v === '') return false
      if (Array.isArray(v)) return v.length > 0
      if (typeof v === 'object') return Object.keys(v as object).length > 0
      return true
    }),
  )
}
