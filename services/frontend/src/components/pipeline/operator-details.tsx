import { useQuery } from '@tanstack/react-query'
import { useId, type ReactNode } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Provenance, Time } from '@/components/provenance'
import { snapshotQuery, type Id, type Operator, type Run } from '@/lib/api'

import { columnRoles, kindLabels, shortName, type SourceInfo } from './labels'

/**
 * Everything about one operator: what it is, what it was given, what its output means, who
 * made it, and, when the run fixed a snapshot of it, which data that was.
 */
export function OperatorDetails({
  operator,
  run,
  sourceOf,
  nameOf,
}: {
  operator: Operator
  /** The card's run, once it is read; null while it is not. */
  run: Run | null
  sourceOf: (operator: Operator) => SourceInfo | undefined
  /** A short name for an input, by id. */
  nameOf: (id: string) => string
}) {
  const headingId = useId()
  const snapshotId = run?.snapshots[operator.id]
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 text-sm">
      <h3 id={headingId} className="flex flex-col gap-0.5">
        <span className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
          {kindLabels[operator.kind]}
        </span>
        <span className="font-semibold break-words">{shortName(operator, sourceOf(operator))}</span>
      </h3>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <Fact term="Id">
          <code className="font-mono text-xs break-all">{operator.id}</code>
        </Fact>
        <Fact term="Stores">
          {operator.materializing
            ? 'A snapshot of its output (materializing)'
            : 'Only its definition; computed from its inputs when read (pass-through)'}
        </Fact>
        {operator.inputs.length > 0 && (
          <Fact term="Reads">
            <ol className="flex flex-col">
              {operator.inputs.map((input, index) => (
                <li key={`${input}-${index}`}>
                  {operator.kind === 'transform' && <code className="mr-1 font-mono text-xs">input_{index}</code>}
                  {nameOf(input)}
                </li>
              ))}
            </ol>
          </Fact>
        )}
        <Fact term="Made by">
          <Provenance actor={operator.created_by} at={operator.created_at} />
        </Fact>
      </dl>

      <Parameters operator={operator} source={sourceOf(operator)} />
      <OutputSchema operator={operator} />
      {run && (operator.materializing || snapshotId) && (
        <SnapshotFacts snapshotId={snapshotId} />
      )}
    </section>
  )
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-neutral-500">{term}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5">
      <h4 id={id} className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
        {title}
      </h4>
      {children}
    </section>
  )
}

function Parameters({ operator, source }: { operator: Operator; source: SourceInfo | undefined }) {
  const params = operator.params as Record<string, unknown>
  switch (operator.kind) {
    case 'source':
      return (
        <Part title="Data source">
          {source ? (
            <p>
              {source.name}
              <br />
              <span className="font-mono text-xs break-all text-neutral-700 dark:text-neutral-300">{source.address}</span>
            </p>
          ) : (
            <p className="text-neutral-500">A registered data source of the project.</p>
          )}
          <p className="text-xs text-neutral-500">
            Data source id <code className="font-mono break-all">{String(params.data_source_id ?? '')}</code>
          </p>
        </Part>
      )
    case 'transform':
      return (
        <Part title="SQL">
          <pre className="max-h-64 overflow-auto rounded-md bg-neutral-100 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-neutral-950">
            {String(params.sql ?? '')}
          </pre>
        </Part>
      )
    case 'input':
      return (
        <Part title="Input slot">
          <p>
            “{String(params.name ?? '')}”: a run may bind another pipeline to it; without a binding it reads its
            default, the operator it reads above.
          </p>
        </Part>
      )
    default:
      return (
        <Part title="Parameters">
          <pre className="max-h-64 overflow-auto rounded-md bg-neutral-100 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-neutral-950">
            {JSON.stringify(params, null, 2)}
          </pre>
        </Part>
      )
  }
}

function OutputSchema({ operator }: { operator: Operator }) {
  const { output } = operator
  const roles = columnRoles(output.roles)
  return (
    <Part title="Output">
      <p className="text-xs text-neutral-500">
        {output.kind === 'table' ? 'A table' : `A ${output.kind}`}
        {output.derived ? ', its columns derived from its inputs' : ''}. The roles say what the columns mean.
      </p>
      {output.columns.length === 0 ? (
        <p className="text-neutral-500">The columns are not known until the data is read.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-neutral-200 dark:border-neutral-800">
                <th scope="col" className="py-1 pr-2 font-medium">
                  Column
                </th>
                <th scope="col" className="py-1 pr-2 font-medium">
                  Type
                </th>
                <th scope="col" className="py-1 font-medium">
                  Role
                </th>
              </tr>
            </thead>
            <tbody>
              {output.columns.map((column) => (
                <tr key={column.name} className="align-top">
                  <th scope="row" className="py-0.5 pr-2 font-mono font-normal break-all">
                    {column.name}
                  </th>
                  <td className="py-0.5 pr-2 text-neutral-600 dark:text-neutral-400">{column.type}</td>
                  <td className="py-0.5">{roles.get(column.name)?.join('; ') ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Part>
  )
}

/** The data the run used for a materializing operator: the evidence behind the numbers. */
function SnapshotFacts({ snapshotId }: { snapshotId: Id | undefined }) {
  const snapshot = useQuery({ ...snapshotQuery(snapshotId ?? ''), enabled: Boolean(snapshotId) })
  return (
    <Part title="Snapshot in this run">
      {!snapshotId ? (
        <p className="text-neutral-500">The run has not fixed a snapshot of it yet; reading its rows below does.</p>
      ) : snapshot.isPending ? (
        <Loading what="the snapshot" />
      ) : snapshot.error ? (
        <ErrorNotice error={snapshot.error} prefix="The snapshot cannot be loaded:" />
      ) : (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
          <Fact term="Fetched">
            <Time value={snapshot.data.fetched_at} />
          </Fact>
          <Fact term="Content hash">
            <code className="font-mono text-xs break-all">{snapshot.data.content_hash}</code>
          </Fact>
          <Fact term="Rows">
            {snapshot.data.row_count === null || snapshot.data.row_count === undefined
              ? 'Not counted'
              : snapshot.data.row_count.toLocaleString()}
          </Fact>
          {snapshot.data.period && (
            <Fact term="Period">
              {snapshot.data.period.start} – {snapshot.data.period.end}
            </Fact>
          )}
          <Fact term="Snapshot id">
            <code className="font-mono text-xs break-all">{snapshot.data.id}</code>
          </Fact>
        </dl>
      )}
    </Part>
  )
}
