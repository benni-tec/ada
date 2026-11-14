import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { lineageQuery, type Operator, type OperatorId, type ReportSource } from '@/lib/api'

const kindLabels: Record<Operator['kind'], string> = {
  source: 'Source',
  extract: 'Extraction',
  input: 'Input',
  transform: 'SQL',
  statistic: 'Statistic',
  agent: 'Agent',
}

/**
 * How a widget's numbers were made: its operator and everything upstream, inputs first.
 * Closed by default and loaded on opening, since most readers only want the number;
 * whoever doubts it can follow it back to the source and its fetch time.
 */
export function Pipeline({ operatorId, sources }: { operatorId: OperatorId; sources: ReportSource[] }) {
  const [open, setOpen] = useState(false)
  return (
    <details
      className="px-4 py-2 text-sm [&:not(:first-child)]:border-t [&:not(:first-child)]:border-neutral-200 dark:[&:not(:first-child)]:border-neutral-800"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-neutral-700 select-none hover:underline dark:text-neutral-300">
        Pipeline
      </summary>
      {open && <Steps operatorId={operatorId} sources={sources} />}
    </details>
  )
}

function Steps({ operatorId, sources }: { operatorId: OperatorId; sources: ReportSource[] }) {
  const { data: operators, error, isPending } = useQuery(lineageQuery(operatorId))
  if (isPending) return <Loading what="the pipeline" />
  if (error) return <ErrorNotice error={error} prefix="The pipeline cannot be loaded:" />
  const byOperator = new Map(sources.map((source) => [source.operator_id, source]))
  return (
    <ol aria-label="Steps, from the sources to the widget" className="mt-2 flex flex-col gap-2">
      {operators.map((operator, index) => (
        <li key={operator.id} className="flex flex-col gap-1 rounded-md bg-neutral-50 px-3 py-2 dark:bg-neutral-950">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-xs text-neutral-500">{index + 1}.</span>
            <span className="font-medium">{kindLabels[operator.kind]}</span>
            <code className="truncate font-mono text-xs text-neutral-500" title={operator.id}>
              {operator.id}
            </code>
          </div>
          <Detail operator={operator} source={byOperator.get(operator.id)} />
        </li>
      ))}
    </ol>
  )
}

function Detail({ operator, source }: { operator: Operator; source: ReportSource | undefined }) {
  const params = operator.params as Record<string, unknown>
  switch (operator.kind) {
    case 'source':
      return source ? (
        <p className="text-xs text-neutral-700 dark:text-neutral-300">
          {source.name} · <span className="font-mono break-all">{source.address}</span>
        </p>
      ) : (
        <p className="text-xs text-neutral-500">A registered data source.</p>
      )
    case 'transform':
      return (
        <pre className="overflow-x-auto rounded bg-white p-2 font-mono text-xs whitespace-pre-wrap dark:bg-neutral-900">
          {String(params.sql ?? '')}
        </pre>
      )
    case 'input':
      return <p className="text-xs text-neutral-700 dark:text-neutral-300">Input slot “{String(params.name ?? '')}”</p>
    default:
      return (
        <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap text-neutral-700 dark:text-neutral-300">
          {JSON.stringify(params, null, 2)}
        </pre>
      )
  }
}
