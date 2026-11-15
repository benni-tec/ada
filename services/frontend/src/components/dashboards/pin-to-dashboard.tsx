import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { History, MessagesSquare, Pin } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

import { useChatDraft, widgetChip } from '@/components/chat/chat-draft'
import { Hint, IconButton } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  createDashboard,
  dashboardKeys,
  dashboardsQuery,
  getDashboard,
  keys,
  pinWidget,
  startSessionFromDashboard,
  widgetQuery,
  type Dashboard,
  type Widget,
} from '@/lib/api'

const NEW = 'new'

const fieldClass =
  'h-8 min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30'

/**
 * Pins a widget to a dashboard of its project. The backend pins a copy (`copied_from`
 * names the original), so the dashboard's widget can be changed on its own and the
 * session's stays as it was. The dashboard can be a new one. The pin is made on the
 * dashboard as it is now, since adding a slot cannot clash with what others did meanwhile.
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
      // The copy is a new widget of the project.
      void queryClient.invalidateQueries({ queryKey: keys.projectWidgets(widget.project_id) })
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
      <IconButton
        label="Add to dashboard"
        aria-expanded={open}
        aria-controls={open ? formId : undefined}
        onClick={() => {
          pin.reset()
          setOpen((value) => !value)
        }}
      >
        <Pin />
      </IconButton>
      {pin.isSuccess && (
        <p role="status" className={`${row} px-1 pb-1 text-xs text-green-800 dark:text-green-300`}>
          A copy is pinned to{' '}
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
          className={`${row} flex flex-col gap-2 border-t px-1 py-2 text-sm`}
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
                <Input id={newNameId} value={newName} onChange={(event) => setNewName(event.target.value)} className="h-8" />
              </div>
            )}
            <div className="flex flex-col gap-1">
              <label htmlFor={slotId} className="text-xs font-medium">
                Slot name
              </label>
              <Input id={slotId} value={slot} onChange={(event) => setSlot(event.target.value)} className="h-8" />
            </div>
            <Button type="submit" size="sm" disabled={!ready || pin.isPending}>
              <Pin data-icon="inline-start" aria-hidden="true" />
              {pin.isPending ? 'Pinning…' : 'Pin'}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The dashboard gets a copy of this widget, which can then be changed on its own. An existing slot of that name
            shows it instead; a new name adds a slot. The dashboard keeps reading the widget’s data sources, so they need a
            refresh policy to stay current.
          </p>
          {dashboards.error && <ErrorNotice error={dashboards.error} prefix="The dashboards cannot be loaded:" />}
          {pin.error && <ErrorNotice error={pin.error} prefix="Not pinned:" />}
        </form>
      )}
    </>
  )
}

/**
 * Talk about a widget. On a dashboard (its grid, or the widget opened over it): a new
 * session with the dashboard attached, the widget on its first message. In a session (a
 * dashboard tab beside it): the widget on this session's message. Elsewhere there is no
 * dashboard to attach, so no icon.
 */
export function TalkAboutWidget({ widget }: { widget: Widget }) {
  const { dashboardId, sessionId } = useParams({ strict: false })
  const draft = useChatDraft()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const start = useMutation({
    mutationFn: () => startSessionFromDashboard(widget.project_id, dashboardId!, `About ${widget.title || 'a widget'}`),
    onSuccess: async (session) => {
      void queryClient.invalidateQueries({ queryKey: keys.sessions(widget.project_id) })
      await navigate({
        to: '/projects/$projectId/sessions/$sessionId',
        params: { projectId: widget.project_id, sessionId: session.id },
        search: { about: widget.id },
      })
    },
  })
  const label = 'Talk about this widget'
  if (sessionId && draft)
    return (
      <IconButton label={label} onClick={() => draft.addChip(widgetChip(widget))}>
        <MessagesSquare />
      </IconButton>
    )
  if (!dashboardId) return null
  return (
    <IconButton
      label={start.error ? `No session started: ${start.error.message}` : 'Talk about this widget in a new session'}
      unavailable={start.isPending ? 'Starting a session…' : undefined}
      onClick={() => start.mutate()}
    >
      <MessagesSquare />
    </IconButton>
  )
}

/**
 * On a dashboard: back to the session the widget was made in, scrolled to it. A widget on
 * a dashboard is usually a copy made by pinning, which has no session of its own: the way
 * back then follows `copied_from` to the original and opens its session at it.
 *
 * Neither made in a session: the icon stays, disabled, and its tooltip says why; an icon
 * that comes and goes between cards would leave people wondering what they are missing.
 * It stays focusable (`aria-disabled`), so the keyboard reaches the reason.
 */
export function GoToSession({ widget }: { widget: Widget }) {
  const copiedFrom = widget.session_id ? null : (widget.copied_from ?? null)
  const original = useQuery({ ...widgetQuery(copiedFrom ?? ''), enabled: copiedFrom !== null })
  const source = widget.session_id ? widget : original.data?.session_id ? original.data : null

  if (!source) {
    return (
      <IconButton label="Go to the session it came from" unavailable={original.isLoading ? 'Looking for the session…' : 'Not made in a session'}>
        <History />
      </IconButton>
    )
  }
  return (
    <Hint label="Go to the session it came from">
      <Button asChild variant="ghost" size="icon-sm">
        <Link
          to="/projects/$projectId/sessions/$sessionId"
          params={{ projectId: source.project_id, sessionId: source.session_id! }}
          search={{ widget: source.id }}
          aria-label="Go to the session it came from"
        >
          <History />
        </Link>
      </Button>
    </Hint>
  )
}
