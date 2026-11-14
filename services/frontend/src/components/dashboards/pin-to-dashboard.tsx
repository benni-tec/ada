import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'

import { AddToDashboardIcon, iconActionClass, SessionIcon, WithTooltip } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import {
  createDashboard,
  dashboardKeys,
  dashboardsQuery,
  getDashboard,
  pinWidget,
  type Dashboard,
  type Widget,
} from '@/lib/api'

const NEW = 'new'

const fieldClass =
  'min-w-0 rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900'

/**
 * Pins a widget to a dashboard of its project: a reference, so the dashboard keeps
 * showing the widget's pipeline at the latest run. The dashboard can be a new one. The
 * pin is made on the dashboard as it is now, since adding a slot cannot clash with what
 * others did meanwhile.
 *
 * An icon in the card's footer line; the chooser and the outcome open as rows of their own
 * below that line (`basis-full`, last in the footer's wrapping row), so the line stays one.
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
      // The outcome replaces the chooser, so the footer is back to its line and one more.
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.list(widget.project_id) })
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.view(dashboard.id) })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    pin.mutate()
  }
  const ready = slot.trim() !== '' && (selected !== NEW || newName.trim() !== '')

  const formId = useId()
  const row = 'order-last basis-full'
  return (
    <>
      <WithTooltip label="Add to dashboard">
        {(labelledBy) => (
          <button
            type="button"
            aria-labelledby={labelledBy}
            aria-expanded={open}
            aria-controls={open ? formId : undefined}
            onClick={() => {
              pin.reset()
              setOpen((value) => !value)
            }}
            className={iconActionClass}
          >
            <AddToDashboardIcon />
          </button>
        )}
      </WithTooltip>
      {pin.isSuccess && (
        <p role="status" className={`${row} pb-1 text-xs text-green-800 dark:text-green-300`}>
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
      {open && (
        <form
          id={formId}
          onSubmit={submit}
          aria-label={`Pin ${widget.title || 'widget'} to a dashboard`}
          className={`${row} flex flex-col gap-2 border-t border-neutral-200 py-2 text-sm dark:border-neutral-800`}
        >
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
    </>
  )
}

/**
 * On a dashboard: back to the session the widget was made in, scrolled to it. A widget
 * made outside a session keeps the icon, disabled, and its tooltip says why: an icon that
 * comes and goes between cards would leave people wondering what they are missing. It
 * stays focusable (`aria-disabled`, not `disabled`), so the keyboard reaches the reason.
 */
export function GoToSession({ widget }: { widget: Widget }) {
  if (!widget.session_id) {
    return (
      <WithTooltip label="Not made in a session">
        {(labelledBy) => (
          <button type="button" aria-labelledby={labelledBy} aria-disabled="true" className={iconActionClass}>
            <SessionIcon />
          </button>
        )}
      </WithTooltip>
    )
  }
  return (
    <WithTooltip label="Go to the session it came from">
      {(labelledBy) => (
        <Link
          to="/projects/$projectId/sessions/$sessionId"
          params={{ projectId: widget.project_id, sessionId: widget.session_id! }}
          search={{ widget: widget.id }}
          aria-labelledby={labelledBy}
          className={iconActionClass}
        >
          <SessionIcon />
        </Link>
      )}
    </WithTooltip>
  )
}
