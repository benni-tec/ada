import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PanelRightClose, PanelRightOpen, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'

import { Hint, IconButton } from '@/components/icon-action'
import { ErrorNotice, Loading } from '@/components/notices'
import { attachmentKeys, attachmentsQuery, detach, type Attachment, type Id } from '@/lib/api'
import { actorLabel } from '@/lib/actors'
import { cn } from '@/lib/utils'

import { AttachChooser } from './attach-chooser'
import { AttachmentView } from './attachment-views'
import { attachmentKinds, attachmentTitle } from './kinds'
import { usePaneWidth } from './pane-width'
import { ResizeHandle } from './resize-handle'

const tabStorageKey = (sessionId: Id) => `ada-session-tab:${sessionId}`

/** The tab last open in this session, in this browser. Storage may be refused (private
 * windows, blocked site data): the newest tab is open then. */
function rememberedTab(sessionId: Id): Id | null {
  try {
    return localStorage.getItem(tabStorageKey(sessionId))
  } catch {
    return null
  }
}

function rememberTab(sessionId: Id, attachmentId: Id) {
  try {
    localStorage.setItem(tabStorageKey(sessionId), attachmentId)
  } catch {
    // Not remembered; the page works without it.
  }
}

// On the bar, which is black on light and white on dark: the page's strongest contrast,
// marking where the attachments begin, apart from the chat.
const onBar =
  'text-white hover:bg-white/15 hover:text-white focus-visible:ring-white/60 dark:text-black dark:hover:bg-black/10 dark:hover:text-black dark:focus-visible:ring-black/50'

/**
 * The right half of a session page: what is attached to the session, as tabs on a black
 * bar, one view at a time. The last tab open is remembered per session. The live stream
 * refetches the list (`session.attachment_added`, `session.attachment_removed`), and an
 * attachment an agent added becomes the open tab, so the person sees what it brought.
 *
 * The pane is open while something is attached and closed while nothing is: it closes
 * when the last attachment goes and opens when one arrives. The person may close or open
 * it either way, empty too. Its width is dragged at its left edge, remembered per browser.
 */
export function AttachmentPanel({ projectId, sessionId }: { projectId: Id; sessionId: Id }) {
  const queryClient = useQueryClient()
  const attachments = useQuery(attachmentsQuery(sessionId))
  const list = attachments.data
  const [picked, setPicked] = useState<Id | null>(() => rememberedTab(sessionId))

  // Whether the pane is open: until something changes it, while anything is attached (or
  // the list cannot be read, so that it says why).
  const [chosenOpen, setOpen] = useState<boolean>()
  // What the list held when last seen: one that appears since, added by an agent, opens.
  // The first list seen opens nothing by itself.
  const [seen, setSeen] = useState<Attachment[]>()
  if (list && list !== seen) {
    if (seen) {
      const before = new Set(seen.map((attachment) => attachment.id))
      const brought = list.findLast((attachment) => !before.has(attachment.id) && attachment.actor.kind !== 'user')
      if (brought) setPicked(brought.id)
      // Something new opens the pane; the last one going closes it.
      if (list.some((attachment) => !before.has(attachment.id))) setOpen(true)
      else if (seen.length > 0 && list.length === 0) setOpen(false)
    }
    setSeen(list)
  }
  const open = chosenOpen ?? (attachments.isError || (list !== undefined && list.length > 0))
  const [width, setWidth] = usePaneWidth()
  // The toggle the person pressed is replaced by the other one: the focus moves to it.
  const toggleRef = useRef<HTMLButtonElement>(null)
  const toggled = useRef(false)
  const toggle = (next: boolean) => {
    toggled.current = true
    setOpen(next)
  }
  useEffect(() => {
    if (toggled.current) toggleRef.current?.focus()
    toggled.current = false
  }, [open])
  const shown = list?.find((attachment) => attachment.id === picked) ?? list?.at(-1)
  const shownId = shown?.id
  useEffect(() => {
    if (shownId) rememberTab(sessionId, shownId)
  }, [sessionId, shownId])

  const setList = (change: (current: Attachment[]) => Attachment[]) =>
    queryClient.setQueryData<Attachment[]>(attachmentKeys.list(sessionId), (current) => current && change(current))
  const added = (attachment: Attachment) => {
    setList((current) => (current.some((other) => other.id === attachment.id) ? current : [...current, attachment]))
    setPicked(attachment.id)
    void queryClient.invalidateQueries({ queryKey: attachmentKeys.list(sessionId) })
  }
  const remove = useMutation({
    mutationFn: (attachment: Attachment) => detach(sessionId, attachment.id),
    onSuccess: (_, attachment) => {
      setList((current) => current.filter((other) => other.id !== attachment.id))
      void queryClient.invalidateQueries({ queryKey: attachmentKeys.list(sessionId) })
    },
    onError: () => {
      toggled.current = false
    },
  })
  const onDetach = (attachment: Attachment) => {
    // Detaching the last one closes the pane: the focus goes to the toggle that opens it.
    toggled.current = list?.length === 1
    // The open tab goes: its neighbour opens, the one before it if there is one.
    if (list && attachment.id === shown?.id) {
      const index = list.indexOf(attachment)
      setPicked((list[index - 1] ?? list[index + 1])?.id ?? null)
    }
    remove.mutate(attachment)
  }

  const panelId = useId()
  const paneId = useId()
  const empty = list?.length === 0
  const chooser = (onBarToo: boolean) => (
    <AttachChooser
      projectId={projectId}
      sessionId={sessionId}
      attachments={list ?? []}
      onAttached={added}
      onOpen={setPicked}
      align={onBarToo ? 'end' : 'center'}
      variant={onBarToo ? 'ghost' : 'outline'}
      className={onBarToo ? onBar : undefined}
    />
  )

  if (!open)
    return (
      <aside
        id={paneId}
        aria-label="Attachments"
        // Closed: the bar's colour, a line under the chat or a strip at the page's right.
        className="flex h-10 shrink-0 items-center gap-2 border-t bg-black px-1.5 text-white lg:h-auto lg:w-10 lg:flex-col lg:border-t-0 lg:border-l lg:px-0 lg:py-1.5 dark:bg-white dark:text-black"
      >
        <IconButton
          ref={toggleRef}
          label="Open the attachments"
          side="left"
          aria-expanded={false}
          aria-controls={paneId}
          onClick={() => toggle(true)}
          className={onBar}
        >
          <PanelRightOpen />
        </IconButton>
        <span className="text-xs font-medium tracking-wide text-white/70 uppercase lg:sr-only dark:text-black/60">
          Attachments
        </span>
        {list && list.length > 0 && (
          <span className="text-xs text-white/70 tabular-nums dark:text-black/60">
            <span className="sr-only">Attached: </span>
            {list.length}
          </span>
        )}
      </aside>
    )

  const close = (
    <IconButton
      ref={toggleRef}
      label="Close the attachments"
      side="bottom"
      aria-expanded={true}
      aria-controls={paneId}
      onClick={() => toggle(false)}
      className={onBar}
    >
      <PanelRightClose />
    </IconButton>
  )

  return (
    <aside
      id={paneId}
      aria-label="Attachments"
      style={{ '--attachments-width': `${width}%` } as CSSProperties}
      className={cn(
        'relative flex min-h-0 min-w-0 flex-col border-t lg:w-(--attachments-width) lg:flex-none lg:border-t-0 lg:border-l',
        // Stacked under the chat on a narrow screen, an empty half takes only its line.
        empty ? 'shrink-0' : 'flex-1',
      )}
    >
      <ResizeHandle width={width} onResize={setWidth} controls={paneId} />
      <header className="flex h-10 shrink-0 items-stretch bg-black text-white dark:bg-white dark:text-black">
        {list && list.length > 0 ? (
          <Tabs
            attachments={list}
            shown={shown}
            panelId={panelId}
            onSelect={setPicked}
            onDetach={onDetach}
            detaching={remove.isPending ? remove.variables?.id : undefined}
          />
        ) : (
          <span className="flex flex-1 items-center px-3 text-xs font-medium tracking-wide text-white/70 uppercase dark:text-black/60">
            Attachments
          </span>
        )}
        <div className="flex shrink-0 items-center gap-0.5 px-1.5">
          {!empty && chooser(true)}
          {close}
        </div>
      </header>
      {remove.error && (
        <div className="border-b px-4 py-2">
          <ErrorNotice error={remove.error} prefix="Not detached:" />
        </div>
      )}
      {attachments.isPending ? (
        <div className="p-4">
          <Loading what="the attachments" />
        </div>
      ) : attachments.error ? (
        <div className="p-4">
          <ErrorNotice error={attachments.error} prefix="The attachments cannot be loaded:" />
        </div>
      ) : shown ? (
        <div
          role="tabpanel"
          id={panelId}
          aria-labelledby={`${panelId}-${shown.id}`}
          className="min-h-0 flex-1 overflow-y-auto p-4"
        >
          {/* Keyed, so a view's own state (a picked operator, an open row) is its tab's. */}
          <AttachmentView key={shown.id} projectId={projectId} attachment={shown} />
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 px-6 py-8 text-center lg:flex-1 lg:justify-center">
          <p className="max-w-sm text-sm text-muted-foreground">
            Nothing is attached. Keep a dashboard, report, alert rule, source, pipeline, session, widget or web page in
            view beside the conversation.
          </p>
          {chooser(false)}
        </div>
      )}
    </aside>
  )
}

/**
 * One tab per attachment: its kind's icon and its title (cut short, whole in the tooltip),
 * and an × that detaches it. The arrow keys, Home and End move between the tabs.
 */
function Tabs({
  attachments,
  shown,
  panelId,
  onSelect,
  onDetach,
  detaching,
}: {
  attachments: Attachment[]
  shown: Attachment | undefined
  panelId: string
  onSelect: (id: Id) => void
  onDetach: (attachment: Attachment) => void
  /** The attachment being detached now. */
  detaching?: Id
}) {
  const list = useRef<HTMLDivElement>(null)
  const tab = (id: Id) =>
    [...(list.current?.querySelectorAll<HTMLElement>('[role="tab"]') ?? [])].find((element) => element.dataset.attachment === id)
  // An agent's new tab may open beyond the bar's end.
  useEffect(() => {
    if (shown) tab(shown.id)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [shown])

  const onKeyDown = (index: number) => (event: KeyboardEvent<HTMLButtonElement>) => {
    const last = attachments.length - 1
    const next =
      event.key === 'ArrowRight'
        ? index === last
          ? 0
          : index + 1
        : event.key === 'ArrowLeft'
          ? index === 0
            ? last
            : index - 1
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? last
              : null
    if (next === null) return
    event.preventDefault()
    onSelect(attachments[next].id)
    tab(attachments[next].id)?.focus()
  }

  return (
    <div
      ref={list}
      role="tablist"
      aria-label="Attachments"
      className="flex min-w-0 flex-1 items-stretch overflow-x-auto [scrollbar-width:none]"
    >
      {attachments.map((attachment, index) => {
        const selected = attachment.id === shown?.id
        const { label, icon: Icon } = attachmentKinds[attachment.kind]
        const title = attachmentTitle(attachment)
        return (
          <div
            key={attachment.id}
            role="presentation"
            className={cn(
              // Tabs share the bar, shrinking to a few words each before it scrolls.
              'relative flex max-w-48 min-w-28 items-center gap-0.5 border-r border-white/10 pr-1 pl-3 transition-colors dark:border-black/10',
              selected
                ? 'bg-white/20 text-white dark:bg-black/10 dark:text-black'
                : 'text-white/65 hover:bg-white/10 hover:text-white dark:text-black/60 dark:hover:bg-black/5 dark:hover:text-black',
            )}
          >
            <Hint
              label={
                <span className="flex flex-col">
                  <span>
                    {label}: {title}
                  </span>
                  <span className="opacity-70">Attached by {actorLabel(attachment.actor)}</span>
                </span>
              }
              side="bottom"
            >
              <button
                type="button"
                role="tab"
                id={`${panelId}-${attachment.id}`}
                data-attachment={attachment.id}
                aria-selected={selected}
                aria-controls={selected ? panelId : undefined}
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelect(attachment.id)}
                onKeyDown={onKeyDown(index)}
                className="flex h-full min-w-0 items-center gap-1.5 rounded-sm text-[0.8rem] font-medium outline-none focus-visible:ring-2 focus-visible:ring-white/70 dark:focus-visible:ring-black/60"
              >
                <Icon aria-hidden="true" className="size-3.5 shrink-0" />
                <span className="truncate">{title}</span>
              </button>
            </Hint>
            <IconButton
              label={`Detach ${title}`}
              size="icon-xs"
              disabled={detaching === attachment.id}
              onClick={() => onDetach(attachment)}
              className={cn(onBar, 'text-current opacity-70 hover:opacity-100')}
            >
              <X />
            </IconButton>
            {selected && <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-0.5 bg-white dark:bg-black" />}
          </div>
        )
      })}
    </div>
  )
}
