import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Badge } from '@/components/ui/badge'
import { webSettingsQuery } from '@/lib/api'

import { SettingsSection } from './form'

/** What the web tools may do: read from the platform's configuration, not editable here. */
export function WebSection() {
  const { data: web, error, isPending } = useQuery(webSettingsQuery())
  return (
    <SettingsSection
      title="Web"
      description="Shared by all projects: agents search the web through ADA’s own Exa key, or its Context.dev key when no Exa key is set, and read pages, extract tables and map sites through its Context.dev key, so nobody needs an account of their own."
    >
      {isPending ? (
        <Loading what="the web settings" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The web settings cannot be loaded:" />
      ) : (
        <>
          <dl className="grid max-w-xl grid-cols-[auto_1fr] items-baseline gap-x-6 gap-y-3 text-sm">
            <dt className="font-medium">Web search</dt>
            <dd>
              <Configured configured={web.search_engine != null}>
                set <code className="font-mono">EXA_API_KEY</code> or <code className="font-mono">CONTEXT_DEV_API_KEY</code>
              </Configured>
              {web.search_engine != null && (
                <span className="ml-2 text-muted-foreground">
                  through {web.search_engine === 'exa' ? 'Exa' : 'Context.dev (no Exa key is set)'}
                </span>
              )}
            </dd>
            <dt className="font-medium">Exa key</dt>
            <dd>
              <Configured configured={web.exa_configured ?? false}>
                set <code className="font-mono">EXA_API_KEY</code>
              </Configured>
            </dd>
            <dt className="font-medium">Context.dev key</dt>
            <dd>
              <Configured configured={web.context_dev_configured}>
                set <code className="font-mono">CONTEXT_DEV_API_KEY</code>
              </Configured>
            </dd>
            <dt className="font-medium">Watching pages</dt>
            <dd>
              <Configured configured={web.watching_configured ?? false}>
                a Context.dev key and <code className="font-mono">ADA_PUBLIC_URL</code>, where Context.dev calls back
              </Configured>
            </dd>
            <dt className="font-medium">Web credits per project per day</dt>
            <dd className="tabular-nums">{web.daily_credit_limit.toLocaleString('en')}</dd>
          </dl>
          <p className="max-w-2xl text-sm text-muted-foreground">
            A search counts 5 credits, reading or mapping a page 1, extracting a table about 5. Expensive operations
            (crawl, extract, answers) are kept as data sources with long minimum refresh intervals: a crawl or an
            extract at most every 7 days, answers at most every 30 days, unless the page is watched. The budget is set
            in the platform’s configuration (<code className="font-mono">WEB_DAILY_CREDIT_LIMIT</code>).
          </p>
        </>
      )}
    </SettingsSection>
  )
}

function Configured({ configured, children }: { configured: boolean; children: ReactNode }) {
  return configured ? (
    <Badge variant="secondary">Configured</Badge>
  ) : (
    <span className="text-muted-foreground">
      Not configured: {children} on the backend and the worker, then restart them.
    </span>
  )
}
