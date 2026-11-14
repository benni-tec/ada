import { useQuery, useQueries } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useId, type ReactNode } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Provenance } from '@/components/provenance'
import { ReportTree } from '@/components/reports/report-tree'
import { SourcesList } from '@/components/reports/sources-list'
import {
  blocksOf,
  compareVersions,
  describeTimeRange,
  reportQuery,
  reportSourcesQuery,
  reportVersionsQuery,
  sessionQuery,
  templateQuery,
  widgetIdsOf,
  widgetQuery,
  type Report,
  type ReportVersion,
} from '@/lib/api'
import { ReportCrumb } from '@/components/breadcrumbs'

type Search = {
  /** The version shown, as its number, e.g. "1.2.0"; the latest without it. */
  version?: string
}

export const Route = createFileRoute('/projects/$projectId/reports/$reportId')({
  staticData: { crumb: ReportCrumb, frozen: true },
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.version === 'string' && search.version !== '' ? { version: search.version } : {},
  component: ReportPage,
})

function ReportPage() {
  const { projectId, reportId } = Route.useParams()
  const { version: asked } = Route.useSearch()
  const navigate = useNavigate()
  const report = useQuery(reportQuery(reportId))
  const versions = useQuery(reportVersionsQuery(reportId))
  const latestNumber = latestOf(report.data, versions.data)?.version

  // Opening the report without a version shows the latest, and the address then names it:
  // a version created while someone reads must not swap the numbers under them. They get
  // the notice below instead.
  useEffect(() => {
    if (!asked && latestNumber) {
      void navigate({
        to: '/projects/$projectId/reports/$reportId',
        params: { projectId, reportId },
        search: { version: latestNumber },
        replace: true,
      })
    }
  }, [asked, latestNumber, navigate, projectId, reportId])

  if (report.isPending || versions.isPending) return <Loading what="the report" />
  if (report.error) return <ErrorNotice error={report.error} prefix="The report cannot be loaded:" />
  if (versions.error) return <ErrorNotice error={versions.error} prefix="The versions cannot be loaded:" />

  const sorted = [...versions.data].sort((a, b) => compareVersions(b.version, a.version))
  const latest = latestOf(report.data, versions.data)
  const shown = asked ? sorted.find((version) => version.version === asked) : latest

  return (
    <article aria-labelledby="report-title" className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 id="report-title" className="text-2xl font-semibold">
            {report.data.name}
          </h1>
          {sorted.length > 0 && <VersionPicker versions={sorted} shown={shown} latest={latest} />}
        </div>
        <Owner report={report.data} />
        {shown && <Frozen version={shown} />}
      </header>
      {!shown ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          This report has no version {asked}.
        </p>
      ) : (
        <>
          {latest && shown.id !== latest.id && (
            <p className="rounded-md border border-neutral-300 bg-neutral-50 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900">
              You are reading version {shown.version}. The latest is{' '}
              <Link
                to="/projects/$projectId/reports/$reportId"
                params={{ projectId: report.data.project_id, reportId }}
                search={{ version: latest.version }}
                className="text-blue-700 underline underline-offset-2 dark:text-blue-400"
              >
                {latest.version}
              </Link>
              .
            </p>
          )}
          <VersionView version={shown} />
        </>
      )}
    </article>
  )
}

function latestOf(report: Report | undefined, versions: ReportVersion[] | undefined) {
  if (!report || !versions?.length) return undefined
  const sorted = [...versions].sort((a, b) => compareVersions(b.version, a.version))
  return sorted.find((version) => version.id === report.latest_version_id) ?? sorted[0]
}

/**
 * Takes the place of the project's "Live" indicator: a version's numbers come from one
 * run and never change, however the data changes later.
 */
function Frozen({ version }: { version: ReportVersion }) {
  const sources = useQuery(reportSourcesQuery(version.id))
  const fetched = (sources.data ?? [])
    .map((source) => source.fetched_at)
    .filter((at): at is string => Boolean(at))
    .sort()
  const day = (at: string) => new Date(at).toLocaleDateString(undefined, { dateStyle: 'medium' })
  const when =
    fetched.length === 0
      ? null
      : day(fetched[0]) === day(fetched.at(-1)!)
        ? day(fetched[0])
        : `${day(fetched[0])} to ${day(fetched.at(-1)!)}`
  return (
    <p
      role="status"
      className="inline-flex w-fit items-center gap-2 rounded-md border border-neutral-300 bg-neutral-50 px-2.5 py-1 text-xs text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
    >
      <span aria-hidden="true" className="size-2 rounded-full bg-neutral-500 dark:bg-neutral-400" />
      Frozen at version {version.version}: these numbers never change.
      {when && <> Data fetched {when}.</>}
    </p>
  )
}

function VersionPicker({
  versions,
  shown,
  latest,
}: {
  versions: ReportVersion[]
  shown: ReportVersion | undefined
  latest: ReportVersion | undefined
}) {
  const { projectId, reportId } = Route.useParams()
  const navigate = useNavigate()
  const fieldId = useId()
  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={fieldId} className="font-medium">
        Version
      </label>
      <select
        id={fieldId}
        value={shown?.version ?? ''}
        onChange={(event) =>
          void navigate({
            to: '/projects/$projectId/reports/$reportId',
            params: { projectId, reportId },
            search: { version: event.target.value },
          })
        }
        className="rounded-md border border-neutral-300 bg-white px-2 py-1 dark:border-neutral-700 dark:bg-neutral-900"
      >
        {!shown && <option value="">Choose a version</option>}
        {versions.map((version) => (
          <option key={version.id} value={version.version}>
            {version.version}
            {version.id === latest?.id ? ' (latest)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function Owner({ report }: { report: Report }) {
  const session = useQuery({ ...sessionQuery(report.session_id ?? ''), enabled: Boolean(report.session_id) })
  if (report.session_id) {
    return (
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Written in the session{' '}
        <Link
          to="/projects/$projectId/sessions/$sessionId"
          params={{ projectId: report.project_id, sessionId: report.session_id }}
          className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
        >
          {session.data?.title ?? 'that produced it'}
        </Link>
      </p>
    )
  }
  if (report.dashboard_id) {
    return (
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Generated from{' '}
        <Link
          to="/projects/$projectId/dashboards/$dashboardId"
          params={{ projectId: report.project_id, dashboardId: report.dashboard_id }}
          className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
        >
          its dashboard
        </Link>
      </p>
    )
  }
  return null
}

function VersionView({ version }: { version: ReportVersion }) {
  const sources = useQuery(reportSourcesQuery(version.id))
  const blocks = blocksOf(version)
  const widgetIds = widgetIdsOf(blocks)
  const widgets = useQueries({ queries: widgetIds.map((id) => widgetQuery(id)) })
  const widgetTitles = new Map(
    widgets.flatMap((query) => (query.data ? [[query.data.id, query.data.title || 'Untitled widget'] as const] : [])),
  )
  const sourcesHeadingId = useId()

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <ReportTree
          blocks={blocks}
          pinned={{
            id: version.run_id,
            frozen: true,
            what: `report version ${version.version}`,
            sources: sources.data ?? [],
          }}
        />
      </div>
      <aside className="flex flex-col gap-6" aria-label="About this version">
        <Facts version={version} />
        <section aria-labelledby={sourcesHeadingId} className="flex flex-col gap-2">
          <h2 id={sourcesHeadingId} className="text-base font-semibold">
            Sources
          </h2>
          {sources.isPending ? (
            <Loading what="the sources" />
          ) : sources.error ? (
            <ErrorNotice error={sources.error} prefix="The sources cannot be loaded:" />
          ) : (
            <SourcesList sources={sources.data} widgetTitles={widgetTitles} />
          )}
        </section>
      </aside>
    </div>
  )
}

/** What makes the version reproducible: its run, its time range and where it came from. */
function Facts({ version }: { version: ReportVersion }) {
  const template = useQuery({ ...templateQuery(version.template_id ?? ''), enabled: Boolean(version.template_id) })
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
      <Fact term="Version">{version.version}</Fact>
      <Fact term="Data period">{describeTimeRange(version.time_range)}</Fact>
      <Fact term="Run">
        <code className="font-mono text-xs break-all" title="Every widget shows this run's data">
          {version.run_id}
        </code>
      </Fact>
      {version.dashboard_version_id && (
        <Fact term="Dashboard version">
          <code className="font-mono text-xs break-all">{version.dashboard_version_id}</code>
        </Fact>
      )}
      {version.template_id && <Fact term="Template">{template.data?.name ?? version.template_id}</Fact>}
      <Fact term="Made by">
        <Provenance actor={version.created_by} at={version.created_at} />
      </Fact>
    </dl>
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
