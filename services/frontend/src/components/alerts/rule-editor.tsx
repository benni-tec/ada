import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent, type ReactNode } from 'react'

import { ConflictNotice, ErrorNotice } from '@/components/notices'
import {
  alertKeys,
  ApiFailure,
  createAlertRule,
  errorMessage,
  operatorQuery,
  projectWidgetsQuery,
  severities,
  updateAlertRule,
  type AlertRule,
  type Column,
  type Id,
  type Severity,
} from '@/lib/api'

import { blank, idFactory, nodeIdOf, asFormula, type FormulaNode } from './formula'
import { FormulaBuilder } from './formula-builder'
import { severityLabels } from './labels'

const fieldClass =
  'rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900'

/** Minutes as typed, to seconds; empty is none. */
function seconds(minutes: string): number | null {
  const value = Number(minutes)
  return minutes.trim() === '' || !Number.isFinite(value) ? null : Math.round(value * 60)
}

function minutes(value: number | null | undefined): string {
  return value ? String(value / 60) : ''
}

/**
 * Creates a rule on a dashboard, or edits one. The measure and key columns are chosen when
 * the rule is created and stay; the formula is built as a tree over the measure's columns.
 * A validation error from the server is shown, and the node it names is marked.
 */
export function RuleEditor({
  projectId,
  dashboardId,
  rule,
  onDone,
}: {
  projectId: Id
  dashboardId: Id
  rule?: AlertRule
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const formId = useId()
  const [name, setName] = useState(rule?.name ?? '')
  const [operatorId, setOperatorId] = useState(rule?.operator_id ?? '')
  const [keyColumns, setKeyColumns] = useState<string[]>(rule?.key_columns ?? [])
  const [severity, setSeverity] = useState<Severity>(rule?.severity ?? 'warning')
  const [interval, setIntervalMinutes] = useState(minutes(rule?.check_interval_seconds))
  const [maxAge, setMaxAge] = useState(minutes(rule?.max_data_age_seconds))
  const [enabled, setEnabled] = useState(rule?.enabled ?? true)
  const [formula, setFormula] = useState<FormulaNode | null>(rule ? asFormula(rule.formula) : null)
  const [conflict, setConflict] = useState<string | null>(null)

  const measure = useQuery({ ...operatorQuery(operatorId), enabled: operatorId !== '' })
  const columns: Column[] = measure.data?.output.columns ?? []
  const timeRole = Boolean(measure.data?.output.roles?.time)
  // A new rule starts from "the first number is below 0" once the measure's columns are known.
  const tree = formula ?? (columns.length > 0 ? blank('compare', columns, idFactory(null), 'root') : null)

  const save = useMutation({
    mutationFn: async (value: FormulaNode) => {
      setConflict(null)
      if (rule) {
        return updateAlertRule(rule.id, {
          expected_revision: rule.revision,
          name,
          formula: value,
          severity,
          // The service keeps an interval it is not given, so clearing one is not possible.
          check_interval_seconds: seconds(interval),
          enabled,
        })
      }
      return createAlertRule(dashboardId, {
        name,
        operator_id: operatorId,
        formula: value,
        key_columns: keyColumns,
        severity,
        check_interval_seconds: seconds(interval),
        max_data_age_seconds: seconds(maxAge),
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: alertKeys.rules() })
      onDone()
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.isConflict) {
        setConflict('Someone else changed this rule while you were editing. Close the editor and open it again.')
        void queryClient.invalidateQueries({ queryKey: alertKeys.rules() })
      }
    },
  })
  const failure = save.error && !(save.error instanceof ApiFailure && save.error.isConflict) ? save.error : null
  const invalidNodeId = failure ? nodeIdOf(errorMessage(failure)) : null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (tree) save.mutate(tree)
  }

  return (
    <form
      aria-label={rule ? `Edit rule ${rule.name}` : 'New alert rule'}
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
    >
      <Field label="Name" htmlFor={`${formId}-name`}>
        <input
          id={`${formId}-name`}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Coverage below target"
          className={fieldClass}
        />
      </Field>
      {rule ? (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          On <span className="font-mono">{rule.operator_id}</span>, one alert per{' '}
          {rule.key_columns.length > 0 ? rule.key_columns.join(' and ') : 'measure'}.
        </p>
      ) : (
        <>
          <MeasurePicker
            projectId={projectId}
            value={operatorId}
            onChange={(id) => {
              // Another measure has other columns: start the condition over.
              setOperatorId(id)
              setFormula(null)
              setKeyColumns([])
            }}
          />
          {measure.error && <ErrorNotice error={measure.error} prefix="The measure cannot be read:" />}
          {columns.length > 0 && (
            <fieldset className="flex flex-col gap-1">
              <legend className="text-sm font-medium">Key columns: one alert per combination</legend>
              <div className="flex flex-wrap gap-3">
                {columns.map((column) => (
                  <label key={column.name} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={keyColumns.includes(column.name)}
                      onChange={(event) =>
                        setKeyColumns(
                          event.target.checked
                            ? [...keyColumns, column.name]
                            : keyColumns.filter((name) => name !== column.name),
                        )
                      }
                    />
                    {column.name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-4">
        <Field label="Severity" htmlFor={`${formId}-severity`}>
          <select
            id={`${formId}-severity`}
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity)}
            className={fieldClass}
          >
            {severities.map((value) => (
              <option key={value} value={value}>
                {severityLabels[value]}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Check every (minutes)"
          htmlFor={`${formId}-interval`}
          hint={rule ? undefined : 'Empty: whenever the data changes'}
        >
          <input
            id={`${formId}-interval`}
            type="number"
            min={1}
            step="any"
            value={interval}
            onChange={(event) => setIntervalMinutes(event.target.value)}
            className={`${fieldClass} w-32`}
          />
        </Field>
        {!rule && (
          <Field label="Maximum data age (minutes)" htmlFor={`${formId}-age`} hint="Older source data is fetched again">
            <input
              id={`${formId}-age`}
              type="number"
              min={1}
              step="any"
              value={maxAge}
              onChange={(event) => setMaxAge(event.target.value)}
              className={`${fieldClass} w-32`}
            />
          </Field>
        )}
        {rule && (
          <label className="flex items-center gap-1.5 self-end text-sm">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            Enabled
          </label>
        )}
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">Condition</legend>
        {tree ? (
          <FormulaBuilder
            value={tree}
            onChange={setFormula}
            columns={columns}
            invalidNodeId={invalidNodeId}
            timeRole={timeRole}
          />
        ) : (
          <p className="text-sm text-neutral-500">Choose a measure to build the condition on its columns.</p>
        )}
      </fieldset>
      {failure && <ErrorNotice error={failure} prefix="Not saved:" />}
      {conflict && <ConflictNotice message={conflict} />}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={save.isPending || !tree || name.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {save.isPending ? 'Saving…' : rule ? 'Save rule' : 'Create rule'}
        </button>
        <button type="button" onClick={onDone} className="rounded-md px-4 py-1.5 text-sm underline underline-offset-2">
          Cancel
        </button>
      </div>
    </form>
  )
}

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-neutral-500">{hint}</p>}
    </div>
  )
}

/** The measure: an operator behind one of the project's widgets, or any operator id. */
function MeasurePicker({ projectId, value, onChange }: { projectId: Id; value: string; onChange: (id: string) => void }) {
  const id = useId()
  const { data: widgets = [] } = useQuery(projectWidgetsQuery(projectId))
  const fromWidgets = new Map(widgets.map((widget) => [widget.operator_id, widget.title || widget.operator_id]))
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`${id}-widget`} className="text-sm font-medium">
        Measure
      </label>
      <div className="flex flex-wrap gap-2">
        <select
          id={`${id}-widget`}
          value={fromWidgets.has(value) ? value : ''}
          onChange={(event) => onChange(event.target.value)}
          className={fieldClass}
        >
          <option value="">The data behind a widget…</option>
          {[...fromWidgets].map(([operatorId, title]) => (
            <option key={operatorId} value={operatorId}>
              {title}
            </option>
          ))}
        </select>
        <input
          aria-label="Measure operator id"
          value={value}
          onChange={(event) => onChange(event.target.value.trim())}
          placeholder="or an operator id, op_…"
          className={`${fieldClass} min-w-0 flex-1 font-mono`}
        />
      </div>
    </div>
  )
}
