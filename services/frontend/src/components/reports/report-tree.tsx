import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { WidgetCard } from '@/components/widget-card'
import { widgetQuery, type Block, type CalloutBlock, type Id, type ReportSource } from '@/lib/api'

import { Pipeline } from './pipeline'

type Pinned = {
  /** The run every widget of the version reads: the same numbers on every visit. */
  runId: Id
  sources: ReportSource[]
}

/**
 * A report version's component tree. Static blocks are words from the author; widget
 * blocks are the only parts that show data, each in its frame pinned to the version's run,
 * with its pipeline one click away.
 */
export function ReportTree({ blocks, pinned }: { blocks: Block[]; pinned: Pinned }) {
  return (
    <div className="flex flex-col gap-4">
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} pinned={pinned} depth={0} />
      ))}
    </div>
  )
}

function BlockView({ block, pinned, depth }: { block: Block; pinned: Pinned; depth: number }) {
  switch (block.type) {
    case 'heading':
      return <Heading level={block.level}>{block.text}</Heading>
    case 'text':
      return <Paragraphs text={block.text} />
    case 'callout':
      return <Callout block={block} />
    case 'widget':
      return <WidgetBlockView widgetId={block.widget_id} caption={block.caption} pinned={pinned} />
    case 'section':
      return (
        <section className="flex flex-col gap-4" aria-label={block.title || undefined}>
          {block.title && <Heading level={Math.min(depth + 2, 3) as 2 | 3}>{block.title}</Heading>}
          {block.blocks.map((child, index) => (
            <BlockView key={index} block={child} pinned={pinned} depth={depth + 1} />
          ))}
        </section>
      )
  }
}

// The page's own title is the h1, so the tree's levels start one below it.
function Heading({ level, children }: { level: 1 | 2 | 3; children: ReactNode }) {
  switch (level) {
    case 1:
      return <h2 className="text-xl font-semibold">{children}</h2>
    case 2:
      return <h3 className="text-lg font-semibold">{children}</h3>
    case 3:
      return <h4 className="font-semibold">{children}</h4>
  }
}

function Paragraphs({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2 leading-relaxed">
      {text.split(/\n\s*\n/).map((paragraph, index) => (
        <p key={index} className="whitespace-pre-line">
          {paragraph}
        </p>
      ))}
    </div>
  )
}

const tones: Record<CalloutBlock['tone'], { label: string; className: string }> = {
  note: {
    label: 'Note',
    className: 'border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100',
  },
  finding: {
    label: 'Finding',
    className:
      'border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100',
  },
  warning: {
    label: 'Warning',
    className:
      'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100',
  },
}

function Callout({ block }: { block: CalloutBlock }) {
  const tone = tones[block.tone] ?? tones.note
  return (
    <aside aria-label={block.title || tone.label} className={`rounded-md border-l-4 px-4 py-3 ${tone.className}`}>
      <p className="text-xs font-semibold tracking-wide uppercase opacity-80">{tone.label}</p>
      {block.title && <p className="font-semibold">{block.title}</p>}
      <Paragraphs text={block.text} />
    </aside>
  )
}

function WidgetBlockView({ widgetId, caption, pinned }: { widgetId: Id; caption: string; pinned: Pinned }) {
  const { data: widget, error, isPending } = useQuery(widgetQuery(widgetId))
  if (isPending) return <Loading what="a widget" />
  if (error) return <ErrorNotice error={error} prefix="A widget cannot be loaded:" />
  return (
    <figure className="flex flex-col gap-1">
      <WidgetCard widget={widget} runId={pinned.runId} linkToWidget={false} />
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800">
        {caption && (
          <figcaption className="px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300">{caption}</figcaption>
        )}
        <Pipeline operatorId={widget.operator_id} sources={pinned.sources} />
        <p className="border-t border-neutral-200 px-4 py-2 text-xs dark:border-neutral-800">
          <Link
            to="/projects/$projectId/widgets/$widgetId"
            params={{ projectId: widget.project_id, widgetId: widget.id }}
            search={{ run: pinned.runId }}
            className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
          >
            Open this widget at the report’s run
          </Link>
        </p>
      </div>
    </figure>
  )
}
