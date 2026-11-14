import { Time } from '@/components/provenance'
import type { Id, ReportSource } from '@/lib/api'

/**
 * The data behind a report version, generated from its widgets' pipelines: each source with
 * the address it was fetched from and when, for the snapshot the version's run used.
 */
export function SourcesList({ sources, widgetTitles }: { sources: ReportSource[]; widgetTitles: Map<Id, string> }) {
  if (sources.length === 0) {
    return <p className="text-sm text-neutral-500">No data sources: this version shows no data.</p>
  }
  return (
    <ol className="flex flex-col gap-3 text-sm">
      {sources.map((source) => (
        <li key={source.operator_id} className="flex flex-col gap-0.5">
          <span className="font-medium">{source.name}</span>
          <Address value={source.address} />
          <span className="text-xs text-neutral-600 dark:text-neutral-400">
            {source.fetched_at ? (
              <>
                Fetched <Time value={source.fetched_at} />
              </>
            ) : (
              'Fetch time not recorded'
            )}
            {source.content_hash && (
              <>
                {' · '}content <code className="font-mono">{source.content_hash.slice(0, 12)}</code>
              </>
            )}
          </span>
          <span className="text-xs text-neutral-500">
            Used by {source.widget_ids.map((id) => `“${widgetTitles.get(id) ?? 'a widget'}”`).join(', ')}
          </span>
        </li>
      ))}
    </ol>
  )
}

function Address({ value }: { value: string }) {
  const web = /^https?:\/\//i.test(value)
  const className = 'font-mono text-xs break-all text-neutral-600 dark:text-neutral-400'
  return web ? (
    <a href={value} target="_blank" rel="noreferrer noopener" className={`${className} hover:underline`}>
      {value}
    </a>
  ) : (
    <span className={className}>{value}</span>
  )
}
