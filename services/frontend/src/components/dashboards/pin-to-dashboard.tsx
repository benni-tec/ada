import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'

import { ErrorNotice } from '@/components/notices'
import { WidgetCardActions } from '@/components/widget-card-actions'
import {
  createDashboard,
  dashboardKeys,
  dashboardsQuery,
  getDashboard,
  pinWidget,
  type Dashboard,
  type Widget,
} from '@/lib/api'

/** Puts "Pin to dashboard" under every widget card inside it. */
export function PinActions({ children }: { children: ReactNode }) {
  return <WidgetCardActions value={(widget) => <PinToDashboard widget={widget} />}>{children}</WidgetCardActions>
}

const NEW = 'new'

const fieldClass =
  'min-w-0 rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900'

/**
 * Pins a widget to a dashboard of its project: a reference, so the dashboard keeps
 * showing the widget's pipeline at the latest run. The dashboard can be a new one. The
 * pin is made on the dashboard as it is now, since adding a slot cannot clash with what
 * others did meanwhile.
 */
export function PinToDashboard({ widget }: { widget: Widget }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const dashboardId = useId()
  const newNameId = useId()
  const slotId = useId()
  const dashboards = useQuery({ ...dashboardsQuery(widget.project_id), enabled: open })
  const [choice, setChoice] = useState<string>('')
  const [newName, setNewName] = useState('')
  const [slot, setSlot] = useState(widget.title)

  // With no choice made yet, the first dashboard, or a new one when there are none.
  const list = dashboards.data ?? []
  const selected = choice || (list.length > 0 ? list[0].id : NEW)

  const pin = useMutation({
    mutationFn: async () => {
      const dashboard: Dashboard =
        selected === NEW
          ? await createDashboard(widget.project_id, newName)
          : (await getDashboard(selected)).dashboard
      const saved = await pinWidget(dashboard, widget.id, slot)
      return saved.dashboard
    },
    onSuccess: (dashboard) => {
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.list(widget.project_id) })
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.view(dashboard.id) })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    pin.mutate()
  }
  const ready = slot.trim() !== '' && (selected !== NEW || newName.trim() !== '')

  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
        >
          Pin to dashboard
        </button>
        {pin.isSuccess && (
          <p role="status" className="text-xs text-green-800 dark:text-green-300">
            Pinned to{' '}
            <Link
              to="/projects/$projectId/dashboards/$dashboardId"
              params={{ projectId: pin.data.project_id, dashboardId: pin.data.id }}
              className="underline underline-offset-2"
            >
              {pin.data.name}
            </Link>
          </p>
        )}
      </div>
      {open && (
        <form onSubmit={submit} aria-label={`Pin ${widget.title || 'widget'} to a dashboard`} className="flex flex-col gap-2">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor={dashboardId} className="text-xs font-medium">
                Dashboard
              </label>
              <select
                id={dashboardId}
                value={selected}
                onChange={(event) => setChoice(event.target.value)}
                disabled={dashboards.isPending}
                className={fieldClass}
              >
                {list.map((dashboard) => (
                  <option key={dashboard.id} value={dashboard.id}>
                    {dashboard.name}
                  </option>
                ))}
                <option value={NEW}>New dashboard…</option>
              </select>
            </div>
            {selected === NEW && (
              <div className="flex flex-col gap-1">
                <label htmlFor={newNameId} className="text-xs font-medium">
                  Name of the new dashboard
                </label>
                <input id={newNameId} value={newName} onChange={(event) => setNewName(event.target.value)} className={fieldClass} />
              </div>
            )}
            <div className="flex flex-col gap-1">
              <label htmlFor={slotId} className="text-xs font-medium">
                Slot name
              </label>
              <input id={slotId} value={slot} onChange={(event) => setSlot(event.target.value)} className={fieldClass} />
            </div>
            <button
              type="submit"
              disabled={!ready || pin.isPending}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
            >
              {pin.isPending ? 'Pinning…' : 'Pin'}
            </button>
          </div>
          <p className="text-xs text-neutral-500">
            An existing slot of that name shows this widget instead; a new name adds a slot. The dashboard keeps reading the
            widget’s data sources, so they need a refresh policy to stay current.
          </p>
          {dashboards.error && <ErrorNotice error={dashboards.error} prefix="The dashboards cannot be loaded:" />}
          {pin.error && <ErrorNotice error={pin.error} prefix="Not pinned:" />}
        </form>
      )}
    </div>
  )
}
