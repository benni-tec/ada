import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'

import { DashboardsSection } from '@/components/dashboards/dashboards-section'
import { EditableTitle } from '@/components/editable-title'
import { ErrorNotice, Loading } from '@/components/notices'
import { Provenance, Time } from '@/components/provenance'
import {
  createSession,
  getProject,
  keys,
  projectQuery,
  projectWidgetsQuery,
  renameProject,
  sessionsQuery,
  sourcesQuery,
  type DataSource,
  type Id,
  type Session,
} from '@/lib/api'
import { useRevisedUpdate } from '@/lib/revisions'

export const Route = createFileRoute('/projects/$projectId/')({
  component: ProjectPage,
})

function ProjectPage() {
  const { projectId } = Route.useParams()
  const { data: project, error, isPending } = useQuery(projectQuery(projectId))
  const rename = useRevisedUpdate({
    queryKey: keys.project(projectId),
    read: () => getProject(projectId),
    update: renameProject,
    describeConflict: (latest) =>
      `Someone else renamed this project while you were editing: it is now “${latest.name}”. ` +
      'Your name was not saved; save again to replace it.',
    alsoInvalidate: [keys.projects()],
  })

  if (isPending) return <Loading what="the project" />
  if (error) return <ErrorNotice error={error} prefix="The project cannot be loaded:" />

  return (
    <div className="flex flex-col gap-8">
      <EditableTitle value={project.name} label="project name" {...rename} />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-8">
          <Sessions projectId={projectId} />
          <DashboardsSection projectId={projectId} />
          <Widgets projectId={projectId} />
        </div>
        <Sources projectId={projectId} />
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  )
}

const listClass =
  'divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800'

function Sessions({ projectId }: { projectId: Id }) {
  const { data: sessions, error, isPending } = useQuery(sessionsQuery(projectId))
  return (
    <Section title="Sessions">
      <CreateSession projectId={projectId} />
      {isPending ? (
        <Loading what="sessions" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The sessions cannot be loaded:" />
      ) : sessions.length === 0 ? (
        <p className="text-sm text-neutral-500">No sessions yet.</p>
      ) : (
        <ul className={listClass}>
          {sessions.map((session) => (
            <li key={session.id}>
              <Link
                to="/projects/$projectId/sessions/$sessionId"
                params={{ projectId, sessionId: session.id }}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-neutral-50 focus-visible:bg-neutral-50 dark:hover:bg-neutral-900 dark:focus-visible:bg-neutral-900"
              >
                <span className="font-medium">{session.title}</span>
                <span className="text-xs text-neutral-500">
                  <Time value={session.created_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function CreateSession({ projectId }: { projectId: Id }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inputId = useId()
  const [title, setTitle] = useState('')
  const create = useMutation({
    mutationFn: (value: string) => createSession(projectId, value),
    onSuccess: async (session) => {
      setTitle('')
      await queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
      await navigate({
        to: '/projects/$projectId/sessions/$sessionId',
        params: { projectId, sessionId: session.id },
      })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (title.trim() !== '') create.mutate(title.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-sm font-medium">
        New session
      </label>
      <div className="flex gap-2">
        <input
          id={inputId}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="The question to explore"
          className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
        <button
          type="submit"
          disabled={create.isPending || title.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {create.isPending ? 'Creating…' : 'Start session'}
        </button>
      </div>
      {create.error && <ErrorNotice error={create.error} prefix="Not created:" />}
    </form>
  )
}

/** Every widget of the project, newest first, made in a session or not. */
function Widgets({ projectId }: { projectId: Id }) {
  const { data: sessions = [] } = useQuery(sessionsQuery(projectId))
  const { data, error, isPending } = useQuery(projectWidgetsQuery(projectId))
  const widgets = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const sessionTitles = new Map(sessions.map((session: Session) => [session.id, session.title]))

  return (
    <Section title="Widgets">
      {isPending ? (
        <Loading what="widgets" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The widgets cannot be loaded:" />
      ) : widgets.length === 0 ? (
        <p className="text-sm text-neutral-500">No widgets yet. Agents create them in sessions.</p>
      ) : (
        <ul className={listClass}>
          {widgets.map((widget) => (
            <li key={widget.id} className="flex flex-col gap-1 px-4 py-3">
              <div className="flex items-center justify-between gap-4">
                <Link
                  to="/projects/$projectId/widgets/$widgetId"
                  params={{ projectId, widgetId: widget.id }}
                  className="font-medium hover:underline"
                >
                  {widget.title || 'Untitled widget'}
                </Link>
                <span className="font-mono text-xs text-neutral-500">{widget.type}</span>
              </div>
              <Provenance actor={widget.created_by} at={widget.created_at} note={widget.note} />
              {widget.session_id && sessionTitles.has(widget.session_id) && (
                <p className="text-xs text-neutral-500">In “{sessionTitles.get(widget.session_id)}”</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

const accessLabels: Record<DataSource['access_kind'], string> = {
  url: 'URL',
  request: 'Request',
  browser: 'Browser',
  document: 'Document',
}

function Sources({ projectId }: { projectId: Id }) {
  const { data: sources, error, isPending } = useQuery(sourcesQuery(projectId))
  return (
    <Section title="Data sources">
      {isPending ? (
        <Loading what="data sources" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The data sources cannot be loaded:" />
      ) : sources.length === 0 ? (
        <p className="text-sm text-neutral-500">No data sources yet. Agents register them over MCP.</p>
      ) : (
        <ul className={listClass}>
          {sources.map((source) => (
            <li key={source.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{source.name}</span>
                <span className="text-xs text-neutral-500">
                  {accessLabels[source.access_kind]} · {source.format.toUpperCase()}
                </span>
              </div>
              <p className="truncate font-mono text-xs text-neutral-500" title={source.address}>
                {source.address}
              </p>
              <p className="text-xs text-neutral-600 dark:text-neutral-400">
                Refresh: {source.freshness.kind}
                {source.last_checked_at && (
                  <>
                    {' · '}checked <Time value={source.last_checked_at} />
                  </>
                )}
              </p>
              {source.last_error && (
                <p className="text-xs text-amber-800 dark:text-amber-300">
                  Last refresh failed: {source.last_error}. Widgets on it show stale data.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
