import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { createDashboard, dashboardKeys, dashboardsQuery, type Id } from '@/lib/api'

import { describeRange } from './ranges'

/** The project page's list of dashboards, with a form to start one. */
export function DashboardsSection({ projectId }: { projectId: Id }) {
  const headingId = useId()
  const { data: dashboards, error, isPending } = useQuery(dashboardsQuery(projectId))
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-lg font-semibold">
        Dashboards
      </h2>
      <CreateDashboard projectId={projectId} />
      {isPending ? (
        <Loading what="dashboards" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The dashboards cannot be loaded:" />
      ) : dashboards.length === 0 ? (
        <p className="text-sm text-neutral-500">No dashboards yet. Pin a widget from a session to start one.</p>
      ) : (
        <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          {dashboards.map((dashboard) => (
            <li key={dashboard.id}>
              <Link
                to="/projects/$projectId/dashboards/$dashboardId"
                params={{ projectId, dashboardId: dashboard.id }}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-neutral-50 focus-visible:bg-neutral-50 dark:hover:bg-neutral-900 dark:focus-visible:bg-neutral-900"
              >
                <span className="flex flex-col">
                  <span className="font-medium">{dashboard.name}</span>
                  <span className="text-xs text-neutral-500">{describeRange(dashboard.default_time_range)}</span>
                </span>
                <span className="text-xs text-neutral-500">
                  <Time value={dashboard.created_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function CreateDashboard({ projectId }: { projectId: Id }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inputId = useId()
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: (value: string) => createDashboard(projectId, value),
    onSuccess: async (dashboard) => {
      setName('')
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.list(projectId) })
      await navigate({
        to: '/projects/$projectId/dashboards/$dashboardId',
        params: { projectId, dashboardId: dashboard.id },
      })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() !== '') create.mutate(name.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-sm font-medium">
        New dashboard
      </label>
      <div className="flex gap-2">
        <input
          id={inputId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="What it keeps an eye on"
          className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
        <button
          type="submit"
          disabled={create.isPending || name.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {create.isPending ? 'Creating…' : 'Create dashboard'}
        </button>
      </div>
      {create.error && <ErrorNotice error={create.error} prefix="Not created:" />}
    </form>
  )
}
