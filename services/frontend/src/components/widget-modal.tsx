import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useRouter, useSearch } from '@tanstack/react-router'

import { widgetQuery, type Id } from '@/lib/api'
import { useProjectRun, type CardRun } from '@/lib/view-run'

import { GoToSession } from './dashboards/pin-to-dashboard'
import { Modal } from './modal'
import { ErrorNotice, Loading } from './notices'
import { WidgetCard } from './widget-card'

/** The widget named by `?open=`, full size in a modal over whatever page is beneath. */
export function WidgetModal({ projectId }: { projectId: Id }) {
  const { open } = useSearch({ strict: false })
  if (!open) return null
  return <OpenWidget key={open} projectId={projectId} widgetId={open} />
}

function OpenWidget({ projectId, widgetId }: { projectId: Id; widgetId: Id }) {
  const router = useRouter()
  const navigate = useNavigate()
  const fromCard = useLocation({ select: (location) => location.state.openRun })
  const widget = useQuery(widgetQuery(widgetId))
  // Opened by a link from elsewhere (no card's run): one run of its own, like the widget page.
  const own = useProjectRun(projectId, fromCard === undefined)
  const run: CardRun = fromCard ?? { id: own.data?.id ?? null, frozen: false, what: 'This view’s current run' }

  const close = () => {
    // Opened from a card here: going back leaves the history as it was before. Opened by
    // a link from elsewhere there is nothing of ours to go back to: the address drops `open`.
    if (fromCard) router.history.back()
    else
      void navigate({
        to: '.',
        search: (previous: Record<string, unknown>) => ({ ...previous, open: undefined }),
        replace: true,
        resetScroll: false,
      })
  }

  return (
    <Modal
      title={widget.data ? widget.data.title || 'Untitled widget' : 'Widget'}
      actions={widget.data && <GoToSession widget={widget.data} />}
      onClose={close}
    >
      <div className="flex h-full min-h-0 flex-col p-3">
        {widget.isPending ? (
          <Loading what="the widget" />
        ) : widget.error ? (
          <ErrorNotice error={widget.error} prefix="The widget cannot be loaded:" />
        ) : (
          <>
            {own.error && <ErrorNotice error={own.error} prefix="The data cannot be read:" />}
            <WidgetCard widget={widget.data} run={run} fill openable={false} />
          </>
        )}
      </div>
    </Modal>
  )
}
