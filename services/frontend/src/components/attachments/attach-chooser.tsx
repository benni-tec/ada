import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { Globe, Paperclip } from 'lucide-react'
import { useId, useState, type ComponentProps, type FormEvent } from 'react'

import { severityLabels } from '@/components/alerts/labels'
import { describeRange } from '@/components/dashboards/ranges'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  attach,
  uploadFile,
  registerSource,
  keys,
  dashboardsQuery,
  errorMessage,
  pipelinesQuery,
  projectAlertRulesQuery,
  projectWidgetsQuery,
  reportsQuery,
  sessionsQuery,
  sourcesQuery,
  type Attachment,
  type AttachmentKind,
  type Id,
} from '@/lib/api'
import { accessLabels, formatLabels } from '@/lib/sources'

import { attachmentKinds } from './kinds'

/** One thing the chooser offers. `matches` are the refs an attachment of it may have: a
 * report is attached by its id and comes back as its latest version. */
type Option = { kind: AttachmentKind; ref: string; name: string; detail: string; keywords: string[]; matches: string[] }

type Listed = { kind: AttachmentKind; query: UseQueryResult<Option[]> }

/** The project's things, by kind, read only while the chooser is open. */
function useOptions(projectId: Id, sessionId: Id, enabled: boolean): Listed[] {
  const option = (kind: AttachmentKind, ref: string, name: string, detail: string, keywords: string[] = []): Option => ({
    kind,
    ref,
    name,
    detail,
    keywords,
    matches: [ref],
  })
  return [
    {
      kind: 'dashboard',
      query: useQuery({
        ...dashboardsQuery(projectId),
        enabled,
        select: (dashboards) =>
          dashboards.map((dashboard) => option('dashboard', dashboard.id, dashboard.name, describeRange(dashboard.default_time_range))),
      }),
    },
    {
      kind: 'report',
      query: useQuery({
        ...reportsQuery(projectId),
        enabled,
        // A report without a version has nothing to show yet.
        select: (reports) =>
          reports.flatMap((report) =>
            report.latest_version_id
              ? [{ ...option('report', report.id, report.name, 'Its latest version'), matches: [report.id, report.latest_version_id] }]
              : [],
          ),
      }),
    },
    {
      kind: 'alert_rule',
      query: useQuery({
        ...projectAlertRulesQuery(projectId),
        enabled,
        select: (groups) =>
          groups.flatMap((group) =>
            group.rules.map((rule) =>
              option('alert_rule', rule.id, rule.name, `${severityLabels[rule.severity]} · ${group.dashboard.name}`),
            ),
          ),
      }),
    },
    {
      kind: 'source',
      query: useQuery({
        ...sourcesQuery(projectId),
        enabled,
        select: (sources) =>
          sources.map((source) =>
            option('source', source.id, source.name, `${accessLabels[source.access_kind]} · ${formatLabels[source.format]}`, [
              source.address,
            ]),
          ),
      }),
    },
    {
      kind: 'operator',
      query: useQuery({
        ...pipelinesQuery(projectId),
        enabled,
        select: (pipelines) =>
          pipelines.map((pipeline) =>
            option(
              'operator',
              pipeline.operator_id,
              pipeline.name,
              pipeline.sources.map((source) => source.name).join(', ') || 'No source',
              pipeline.output.columns.map((column) => column.name),
            ),
          ),
      }),
    },
    {
      kind: 'session',
      query: useQuery({
        ...sessionsQuery(projectId),
        enabled,
        select: (sessions) =>
          sessions
            .filter((session) => session.id !== sessionId)
            .map((session) => option('session', session.id, session.title, delegatedLabels[session.agent] ?? 'Session')),
      }),
    },
    {
      kind: 'widget',
      query: useQuery({
        ...projectWidgetsQuery(projectId),
        enabled,
        // This session's own widgets are in its record already.
        select: (widgets) =>
          widgets
            .filter((widget) => widget.session_id !== sessionId)
            .map((widget) => option('widget', widget.id, widget.title || 'Untitled widget', widget.type)),
      }),
    },
  ]
}

/** A web page is kept by its address, which must be a whole http(s) URL. */
function checkUrl(text: string): string | null {
  if (text.length > 2048) return 'The address is longer than 2,048 characters.'
  try {
    const url = new URL(text)
    return url.protocol === 'http:' || url.protocol === 'https:' ? null : 'Give an address that starts with http:// or https://.'
  } catch {
    return 'Give an address that starts with http:// or https://.'
  }
}

/**
 * "Attach": a searchable list of the project's dashboards, reports, alert rules, sources,
 * pipelines, sessions and widgets, and a field for a web page's address. Choosing one
 * attaches it to the session; one already attached is opened instead.
 */
const delegatedLabels: Record<string, string> = { research: 'Research', analysis: 'Analysis' }

export function AttachChooser({
  projectId,
  sessionId,
  attachments,
  onAttached,
  onOpen,
  align = 'end',
  variant = 'outline',
  className,
}: {
  projectId: Id
  sessionId: Id
  attachments: readonly Attachment[]
  /** Attached just now (or found attached already, which the server answers alike). */
  onAttached: (attachment: Attachment) => void
  onOpen: (attachmentId: Id) => void
  align?: ComponentProps<typeof PopoverContent>['align']
  variant?: ComponentProps<typeof Button>['variant']
  className?: string
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [urlProblem, setUrlProblem] = useState<string | null>(null)
  const urlHintId = useId()
  const listed = useOptions(projectId, sessionId, open)
  const add = useMutation({
    mutationFn: ({ kind, ref }: { kind: AttachmentKind; ref: string }) => attach(sessionId, kind, ref),
    onSuccess: (attachment) => {
      setOpen(false)
      setUrl('')
      onAttached(attachment)
    },
  })

  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (!file.name.toLowerCase().endsWith('.csv')) throw new Error('Choose a CSV file.')
      if (!file.size || file.size > 50 * 1024 * 1024) throw new Error('Choose a nonempty CSV up to 50 MiB.')
      const stored = await uploadFile(projectId, file)
      const source = await registerSource(projectId, {
        name: file.name,
        address: stored.address,
        access_kind: 'url',
        format: 'csv',
      })
      return attach(sessionId, 'source', source.id)
    },
    onSuccess: (attachment) => {
      void queryClient.invalidateQueries({ queryKey: keys.sources(projectId) })
      setOpen(false)
      onAttached(attachment)
    },
  })

  const attachedAs = (option: Option) =>
    attachments.find((attachment) => attachment.kind === option.kind && option.matches.includes(attachment.ref))
  const choose = (option: Option) => {
    const existing = attachedAs(option)
    if (existing) {
      setOpen(false)
      onOpen(existing.id)
    } else add.mutate({ kind: option.kind, ref: option.ref })
  }
  const attachUrl = (event: FormEvent) => {
    event.preventDefault()
    const address = url.trim()
    const problem = checkUrl(address)
    setUrlProblem(problem)
    if (problem) return
    const existing = attachments.find((attachment) => attachment.kind === 'web_page' && attachment.ref === address)
    if (existing) {
      setOpen(false)
      setUrl('')
      onOpen(existing.id)
    } else add.mutate({ kind: 'web_page', ref: address })
  }
  const loading = listed.some(({ query }) => query.isPending)

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) {
          add.reset()
          upload.reset()
          setUrlProblem(null)
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button type="button" variant={variant} size="sm" className={className} aria-haspopup="dialog">
          <Paperclip aria-hidden="true" data-icon="inline-start" />
          Attach
        </Button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-[min(28rem,calc(100vw-2rem))] p-0">
        <div className="border-b p-3">
          <label className="flex flex-col gap-2 text-sm">
            Upload CSV
            <Input
              type="file"
              accept=".csv,text/csv"
              disabled={upload.isPending || add.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) upload.mutate(file)
                event.target.value = ''
              }}
            />
          </label>
          {upload.isPending && <p role="status" className="mt-2 text-xs">Uploading and attaching…</p>}
          {upload.error && <p role="alert" className="mt-2 text-xs text-destructive">Not attached: {errorMessage(upload.error)}</p>}
        </div>
        <Command
          label="Search what to attach"
          // The name, the kind and the details: people remember any of them.
          filter={(value, search, keywords) =>
            [value, ...(keywords ?? [])].join(' ').toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput placeholder="Search dashboards, reports, sources…" />
          <CommandList>
            {loading && (
              <p role="status" className="px-3 pt-2 text-xs text-muted-foreground">
                Loading the project…
              </p>
            )}
            {!loading && <CommandEmpty>Nothing in this project matches.</CommandEmpty>}
            {listed.map(({ kind, query }) => {
              const { label, plural, icon: Icon } = attachmentKinds[kind]
              if (query.error)
                return (
                  <p key={kind} role="alert" className="px-3 py-1.5 text-xs text-destructive">
                    The {plural.toLowerCase()} cannot be loaded: {errorMessage(query.error)}
                  </p>
                )
              if (!query.data?.length) return null
              return (
                <CommandGroup key={kind} heading={plural}>
                  {query.data.map((option) => {
                    const attached = attachedAs(option)
                    return (
                      <CommandItem
                        key={option.ref}
                        value={`${option.name} ${kind} ${option.ref}`}
                        keywords={[label, option.detail, ...option.keywords]}
                        data-checked={attached ? true : undefined}
                        disabled={add.isPending || upload.isPending}
                        onSelect={() => choose(option)}
                        className="items-start"
                      >
                        <Icon aria-hidden="true" className="mt-0.5" />
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="truncate font-medium">{option.name}</span>
                          <span className="truncate text-xs text-muted-foreground">
                            {attached ? `Attached · ${option.detail}` : option.detail}
                          </span>
                        </span>
                      </CommandItem>
                    )
                  })}
                </CommandGroup>
              )
            })}
          </CommandList>
        </Command>
        <form aria-label="Attach a web page" onSubmit={attachUrl} className="flex flex-col gap-1.5 border-t p-2">
          <div className="flex items-center gap-2">
            <Globe aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
            <Input
              type="url"
              inputMode="url"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value)
                setUrlProblem(null)
              }}
              placeholder="https://… a web page"
              aria-label="Web page address"
              aria-invalid={urlProblem ? true : undefined}
              aria-describedby={urlProblem ? urlHintId : undefined}
              className="h-8"
            />
            <Button type="submit" size="sm" variant="secondary" disabled={!url.trim() || add.isPending || upload.isPending}>
              Attach
            </Button>
          </div>
          {urlProblem && (
            <p id={urlHintId} className="text-xs text-destructive">
              {urlProblem}
            </p>
          )}
        </form>
        {add.isPending && (
          <p role="status" className="border-t px-3 py-2 text-xs text-muted-foreground">
            Attaching…
          </p>
        )}
        {add.error && (
          <p role="alert" className="border-t px-3 py-2 text-xs text-destructive">
            Not attached: {errorMessage(add.error)}
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
