import { useQuery } from '@tanstack/react-query'

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
      description="Shared by all projects: agents explore the web (search, read a page, map a site) through ADA’s own Context.dev key, so nobody needs an account of their own."
    >
      {isPending ? (
        <Loading what="the web settings" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The web settings cannot be loaded:" />
      ) : (
        <>
          <dl className="grid max-w-xl grid-cols-[auto_1fr] items-baseline gap-x-6 gap-y-3 text-sm">
            <dt className="font-medium">Context.dev key</dt>
            <dd>
              {web.context_dev_configured ? (
                <Badge variant="secondary">Configured</Badge>
              ) : (
                <span className="text-muted-foreground">
                  Not configured: set <code className="font-mono">CONTEXT_DEV_API_KEY</code> on the backend and the
                  worker, then restart them.
                </span>
              )}
            </dd>
            <dt className="font-medium">Context.dev credits per project per day</dt>
            <dd className="tabular-nums">{web.daily_credit_limit.toLocaleString('en')}</dd>
          </dl>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Expensive operations (crawl, answers) are only available as data sources, with long minimum refresh
            intervals: a crawl at most every 7 days, answers at most every 30 days. The budget is set in the platform’s
            configuration (<code className="font-mono">WEB_DAILY_CREDIT_LIMIT</code>).
          </p>
        </>
      )}
    </SettingsSection>
  )
}
