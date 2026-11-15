import { useQuery } from '@tanstack/react-query'
import { CircleAlert, ExternalLink, Settings } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'

import { AlertTable } from '@/components/alerts/alert-table'
import { asFormula, describe } from '@/components/alerts/formula'
import { intervalText, severityTextClasses } from '@/components/alerts/labels'
import { SeverityBadge } from '@/components/alerts/severity'
import { DashboardPanel } from '@/components/dashboards/dashboard-panel'
import { LiveTime } from '@/components/live-time'
import { WatchInterval } from '@/components/watch-interval'
import { ErrorNotice, Loading } from '@/components/notices'
import { kindLabels, shortName, type SourceInfo } from '@/components/pipeline/labels'
import { PipelineGraph } from '@/components/pipeline/pipeline-graph'
import { RowsPreview } from '@/components/pipeline/rows-preview'
import { SourceProvenance, Time } from '@/components/provenance'
import { ReportTree } from '@/components/reports/report-tree'
import { SessionRecord } from '@/components/session-record'
import { Button } from '@/components/ui/button'
import { WidgetCard } from '@/components/widget-card'
import {
  alertFeedQuery,
  alertRuleQuery,
  blocksOf,
  describeTimeRange,
  entriesQuery,
  lineageQuery,
  pipelinesQuery,
  reportQuery,
  reportSourcesQuery,
  reportVersionQuery,
  sessionQuery,
  sessionWidgetsQuery,
  sourcesQuery,
  widgetQuery,
  type Attachment,
  type Id,
  type Operator,
  type OperatorId,
} from '@/lib/api'
import { withSettings } from '@/lib/settings-sections'
import { accessLabels, describeFreshness, formatLabels } from '@/lib/sources'
import { useProjectRun, type CardRun } from '@/lib/view-run'

import { attachmentTitle } from './kinds'
import { OpenLink, ViewBar } from './view-bar'

/** The session's run, which its record reads too: a tab shows the same cut as the chat. */
function useSessionRun(projectId: Id): CardRun {
  const run = useProjectRun(projectId)
  return { id: run.data?.id ?? null, frozen: false, what: 'The session’s current run' }
}

/** What one tab shows, by the kind of thing attached. */
export function AttachmentView({ projectId, attachment }: { projectId: Id; attachment: Attachment }) {
  switch (attachment.kind) {
    case 'dashboard':
      return <DashboardPanel dashboardId={attachment.ref} />
    case 'report':
      return <ReportView projectId={projectId} versionId={attachment.ref} />
    case 'alert_rule':
      return <AlertRuleView projectId={projectId} ruleId={attachment.ref} />
    case 'source':
      return <SourceView projectId={projectId} sourceId={attachment.ref} />
    case 'operator':
      return <OperatorView projectId={projectId} operatorId={attachment.ref} />
    case 'session':
      return <SessionView projectId={projectId} sessionId={attachment.ref} />
    case 'widget':
      return <WidgetView projectId={projectId} widgetId={attachment.ref} />
    case 'web_page':
      return <WebPageView attachment={attachment} />
  }
}

/** A report version, frozen at its run: every widget shows the numbers it was written with. */
function ReportView({ projectId, versionId }: { projectId: Id; versionId: Id }) {
  const version = useQuery(reportVersionQuery(versionId))
  const report = useQuery({ ...reportQuery(version.data?.report_id ?? ''), enabled: version.isSuccess })
  const sources = useQuery(reportSourcesQuery(versionId))
  if (version.isPending) return <Loading what="the report" />
  if (version.error) return <ErrorNotice error={version.error} prefix="The report cannot be loaded:" />
  const shown = version.data
  const newer = report.data?.latest_version_id && report.data.latest_version_id !== shown.id
  return (
    <div className="flex flex-col gap-4">
      <ViewBar
        open={
          <OpenLink
            label="Open the report"
            to="/projects/$projectId/reports/$reportId"
            params={{ projectId, reportId: shown.report_id }}
            search={{ version: shown.version }}
          />
        }
      >
        <span>Frozen at version {shown.version}: these numbers never change.</span>
        <span>{describeTimeRange(shown.time_range)}</span>
      </ViewBar>
      {newer && <p className="text-xs text-muted-foreground">The report has a newer version; this tab keeps the one attached.</p>}
      <ReportTree
        blocks={blocksOf(shown)}
        pinned={{ id: shown.run_id, frozen: true, what: `report version ${shown.version}`, sources: sources.data ?? [] }}
      />
    </div>
  )
}

/** An alert rule and the alerts it raised, as on the alerts page. */
function AlertRuleView({ projectId, ruleId }: { projectId: Id; ruleId: Id }) {
  const rule = useQuery(alertRuleQuery(ruleId))
  const feed = useQuery(alertFeedQuery(projectId))
  const alerts = useMemo(() => (feed.data ?? []).filter((view) => view.rule.id === ruleId), [feed.data, ruleId])
  if (rule.isPending) return <Loading what="the alert rule" />
  if (rule.error) return <ErrorNotice error={rule.error} prefix="The alert rule cannot be loaded:" />
  const active = alerts.filter((view) => view.alert.state === 'firing').length
  return (
    <div className="flex flex-col gap-4">
      <ViewBar open={<OpenLink label="Open the alerts" to="/projects/$projectId/alerts" params={{ projectId }} />}>
        <SeverityBadge severity={rule.data.severity} />
        {!rule.data.enabled && <span className="rounded-full bg-muted px-2 py-0.5">Disabled</span>}
        <span>
          Checked {intervalText(rule.data.check_interval_seconds)}
          {rule.data.last_checked_at ? (
            <>
              {' · last '}
              <LiveTime value={rule.data.last_checked_at} />
            </>
          ) : (
            ' · not checked yet'
          )}
        </span>
      </ViewBar>
      <p className="text-sm">
        Alerts when <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{describe(asFormula(rule.data.formula))}</code>
        {rule.data.key_columns.length > 0 && <span className="text-muted-foreground">, per {rule.data.key_columns.join(' and ')}</span>}
      </p>
      {feed.isPending ? (
        <Loading what="its alerts" />
      ) : feed.error ? (
        <ErrorNotice error={feed.error} prefix="The alerts cannot be loaded:" />
      ) : alerts.length === 0 ? (
        <p className="text-sm text-muted-foreground">It has raised no alerts.</p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className={active > 0 ? `text-sm ${severityTextClasses[rule.data.severity]}` : 'text-sm text-muted-foreground'}>
            {active > 0 ? `${active} active` : 'None active'}
            {alerts.length > active && `, ${alerts.length - active} ended`}
          </p>
          <AlertTable views={alerts} keyColumns={rule.data.key_columns} label={`Alerts of ${rule.data.name}`} />
        </div>
      )}
    </div>
  )
}

/** Where a source operator's data comes from, by the project's sources as they are now. */
function useSourceOf(projectId: Id) {
  const { data: sources } = useQuery(sourcesQuery(projectId))
  return useCallback(
    (operator: Operator): SourceInfo | undefined => {
      if (operator.kind !== 'source') return undefined
      const id = (operator.params as Record<string, unknown>).data_source_id
      const source = sources?.find((candidate) => candidate.id === id)
      return source && { name: source.name, address: source.address }
    },
    [sources],
  )
}

/** A data source: where it comes from, how fresh it is, and its first rows. */
function SourceView({ projectId, sourceId }: { projectId: Id; sourceId: Id }) {
  const sources = useQuery(sourcesQuery(projectId))
  if (sources.isPending) return <Loading what="the source" />
  if (sources.error) return <ErrorNotice error={sources.error} prefix="The source cannot be loaded:" />
  const source = sources.data.find((candidate) => candidate.id === sourceId)
  if (!source) return <p className="text-sm text-muted-foreground">This source is no longer in the project.</p>
  return (
    <div className="flex flex-col gap-4">
      <ViewBar
        open={
          <OpenLink
            label="Manage in Settings"
            icon={<Settings />}
            to="."
            search={withSettings('data-sources')}
            hash={`source-${source.id}`}
            resetScroll={false}
          />
        }
      >
        <span>
          {accessLabels[source.access_kind]} · {formatLabels[source.format]}
        </span>
        <span>
          Refresh {describeFreshness(source.freshness)}
          <WatchInterval source={source} />
          {source.last_checked_at && (
            <>
              {' · '}last checked <LiveTime value={source.last_checked_at} />
            </>
          )}
        </span>
      </ViewBar>
      <p className="truncate font-mono text-xs text-muted-foreground" title={source.address}>
        {source.address}
      </p>
      {source.provenance && <SourceProvenance provenance={source.provenance} />}
      {source.last_error && (
        <p className="flex items-start gap-1 text-xs text-amber-800 dark:text-amber-300">
          <CircleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          Last refresh failed: {source.last_error}. Widgets on it show stale data.
        </p>
      )}
      <SourceRows projectId={projectId} sourceId={source.id} />
    </div>
  )
}

/**
 * The source's first rows, in the session's run. Rows are read through an operator, so
 * this finds the source operator of a pipeline that reads the source; a source no pipeline
 * reads has none to show yet.
 */
function SourceRows({ projectId, sourceId }: { projectId: Id; sourceId: Id }) {
  const run = useSessionRun(projectId)
  const pipelines = useQuery(pipelinesQuery(projectId))
  const reader = pipelines.data?.find((pipeline) => pipeline.sources.some((source) => source.data_source_id === sourceId))
  const lineage = useQuery({ ...lineageQuery(reader?.operator_id ?? ''), enabled: reader !== undefined })
  const operator = lineage.data?.find(
    (candidate) => candidate.kind === 'source' && (candidate.params as Record<string, unknown>).data_source_id === sourceId,
  )
  if (pipelines.isPending || (reader && lineage.isPending)) return <Loading what="its rows" />
  if (pipelines.error) return <ErrorNotice error={pipelines.error} prefix="Its rows cannot be found:" />
  if (lineage.error) return <ErrorNotice error={lineage.error} prefix="Its rows cannot be found:" />
  if (!operator) return <p className="text-sm text-muted-foreground">No pipeline reads this source yet, so it has no rows to show.</p>
  return <RowsBox runId={run.id} operatorId={operator.id} />
}

function RowsBox({ runId, operatorId }: { runId: Id | null; operatorId: OperatorId }) {
  return (
    // As tall as its rows, up to a screenful; then the table scrolls inside.
    <div className="flex max-h-80 flex-col overflow-hidden rounded-md border">
      <RowsPreview key={operatorId} runId={runId} operatorId={operatorId} />
    </div>
  )
}

/** A pipeline: its graph from the sources to its end, and the rows of the operator picked. */
function OperatorView({ projectId, operatorId }: { projectId: Id; operatorId: OperatorId }) {
  const run = useSessionRun(projectId)
  const lineage = useQuery(lineageQuery(operatorId))
  const sourceOf = useSourceOf(projectId)
  const [picked, setPicked] = useState<OperatorId>(operatorId)
  if (lineage.isPending) return <Loading what="the pipeline" />
  if (lineage.error) return <ErrorNotice error={lineage.error} prefix="The pipeline cannot be loaded:" />
  const byId = new Map(lineage.data.map((operator) => [operator.id, operator]))
  const end = byId.get(operatorId) ?? lineage.data[lineage.data.length - 1]
  const selected = byId.get(picked) ?? end
  const nameOf = (operator: Operator) => `${kindLabels[operator.kind]}: ${shortName(operator, sourceOf(operator))}`
  return (
    <div className="flex flex-col gap-3">
      <ViewBar>
        <span>
          {lineage.data.length} operator{lineage.data.length === 1 ? '' : 's'} · ends in {end.output.columns.length} column
          {end.output.columns.length === 1 ? '' : 's'}
        </span>
      </ViewBar>
      <div className="h-96 overflow-hidden rounded-md border">
        {/* No widget reads it here, so no node is marked as the widget's. */}
        <PipelineGraph operators={lineage.data} target="" selected={selected.id} onSelect={setPicked} sourceOf={sourceOf} />
      </div>
      <h3 className="text-sm font-semibold">Rows: {nameOf(selected)}</h3>
      <RowsBox runId={run.id} operatorId={selected.id} />
    </div>
  )
}

/** Another session's record, read only, with its widgets at this session's run. */
function SessionView({ projectId, sessionId }: { projectId: Id; sessionId: Id }) {
  const run = useSessionRun(projectId)
  const session = useQuery(sessionQuery(sessionId))
  const entries = useQuery(entriesQuery(sessionId))
  const widgets = useQuery(sessionWidgetsQuery(sessionId))
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  return (
    <div className="flex flex-col gap-4">
      <ViewBar
        open={<OpenLink label="Open the session" to="/projects/$projectId/sessions/$sessionId" params={{ projectId, sessionId }} />}
      >
        <span>Read only</span>
        {session.data && (
          <span>
            Started <Time value={session.data.created_at} />
          </span>
        )}
      </ViewBar>
      {entries.isPending ? (
        <Loading what="its record" />
      ) : entries.error ? (
        <ErrorNotice error={entries.error} prefix="Its record cannot be loaded:" />
      ) : (
        <SessionRecord
          projectId={projectId}
          entries={entries.data}
          widgets={widgetsById}
          run={run}
          empty="Nothing has happened in this session yet."
        />
      )}
    </div>
  )
}

/** A widget from elsewhere, at the session's run. */
function WidgetView({ projectId, widgetId }: { projectId: Id; widgetId: Id }) {
  const run = useSessionRun(projectId)
  const widget = useQuery(widgetQuery(widgetId))
  if (widget.isPending) return <Loading what="the widget" />
  if (widget.error) return <ErrorNotice error={widget.error} prefix="The widget cannot be loaded:" />
  return <WidgetCard widget={widget.data} run={run} />
}

/** A web page: its address and the way to it. Nothing is framed: most sites refuse it. */
function WebPageView({ attachment }: { attachment: Attachment }) {
  const address = attachment.ref
  return (
    <div className="flex flex-col items-start gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h3 className="text-base font-semibold break-words">{attachmentTitle(attachment)}</h3>
        <a
          href={address}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-xs break-all text-muted-foreground underline-offset-2 hover:underline"
        >
          {address}
        </a>
      </div>
      <Button asChild size="sm">
        <a href={address} target="_blank" rel="noopener noreferrer">
          <ExternalLink aria-hidden="true" data-icon="inline-start" />
          Open <span className="sr-only">in a new tab</span>
        </a>
      </Button>
      <p className="text-xs text-muted-foreground">It opens in a new tab: most sites refuse to be shown inside another page.</p>
    </div>
  )
}
