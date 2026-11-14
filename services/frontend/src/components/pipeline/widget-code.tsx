import { useQuery } from '@tanstack/react-query'
import { useId, type ReactNode } from 'react'

import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockTitle,
} from '@/components/ui/code-block'
import { lineageQuery, type Operator, type OperatorId, type Widget } from '@/lib/api'

import { kindLabels, shortName, type SourceInfo } from './labels'

function Part({ title, children }: { title: string; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5">
      <h3 id={id} className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

/** Read only, with line numbers: the frame names the line an error came from. */
function Source({ title, text }: { title: string; text: string }) {
  return (
    <CodeBlock size="sm" aria-label={title}>
      <CodeBlockHeader>
        <CodeBlockTitle>{title}</CodeBlockTitle>
        <CodeBlockActions>
          <CodeBlockCopyButton value={text} />
        </CodeBlockActions>
      </CodeBlockHeader>
      <CodeBlockContent lineNumbers>{text}</CodeBlockContent>
    </CodeBlock>
  )
}

/** An input's operator in a few words; its own pipeline is read for it. */
function InputOperator({ id, sourceOf }: { id: OperatorId; sourceOf: (operator: Operator) => SourceInfo | undefined }) {
  const lineage = useQuery(lineageQuery(id))
  const operator = lineage.data?.find((candidate) => candidate.id === id)
  return (
    <span className="flex min-w-0 flex-col">
      {operator && (
        <span className="break-words">
          {kindLabels[operator.kind]}: {shortName(operator, sourceOf(operator))}
        </span>
      )}
      <code className="font-mono text-xs break-all text-neutral-500">{id}</code>
    </span>
  )
}

/**
 * What a custom widget draws with: the inputs its code reads by name, each with its
 * operator ("main" is the widget's own), then its code and CSS as the agent wrote them.
 */
export function WidgetCode({
  widget,
  sourceOf,
}: {
  widget: Widget
  sourceOf: (operator: Operator) => SourceInfo | undefined
}) {
  const spec = widget.spec as Record<string, unknown>
  const code = typeof spec.code === 'string' ? spec.code : ''
  const css = typeof spec.css === 'string' ? spec.css : ''
  const libraries = Array.isArray(spec.libraries) ? spec.libraries.map(String) : []
  const inputs = { main: widget.operator_id, ...widget.inputs }
  return (
    <div className="flex flex-col gap-4 p-4 text-sm">
      <Part title="Inputs">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
          {Object.entries(inputs).map(([name, id]) => (
            <div key={name} className="contents">
              <dt>
                <code className="font-mono text-xs">{name}</code>
              </dt>
              <dd className="min-w-0">
                <InputOperator id={id} sourceOf={sourceOf} />
              </dd>
            </div>
          ))}
        </dl>
      </Part>
      {libraries.length > 0 && (
        <Part title="Libraries">
          <p className="font-mono text-xs">{libraries.join(', ')}</p>
        </Part>
      )}
      <Source title="Code" text={code} />
      {css && <Source title="CSS" text={css} />}
    </div>
  )
}
