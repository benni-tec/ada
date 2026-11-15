import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from '@tanstack/react-router'
import { CircleAlert, Eye, EyeOff, FileUp, Pencil, Plus, RefreshCw } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'

import { IconButton } from '@/components/icon-action'
import { LiveTime } from '@/components/live-time'
import { WatchInterval } from '@/components/watch-interval'
import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { SourceProvenance } from '@/components/provenance'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiFailure,
  keys,
  refreshSource,
  registerSource,
  sourcesQuery,
  unwatchSource,
  updateSource,
  uploadFile,
  watchSource,
  webSettingsQuery,
  type AccessKind,
  type DataFormat,
  type DataSource,
  type FreshnessKind,
  type FreshnessPolicy,
  type Id,
} from '@/lib/api'
import { accessLabels, describeFreshness, formatLabels, freshnessLabels } from '@/lib/sources'

import { Field, selectClass, SettingsSection } from './form'

const isConflict = (error: unknown) => error instanceof ApiFailure && error.isConflict

/**
 * This project's data sources: where each reads from, how fresh it is kept and how its
 * last refresh went; added (or uploaded, for a PDF), edited and refreshed here. A link
 * names one with `#source-<id>`.
 */
export function DataSourcesSection({ projectId }: { projectId: Id }) {
  const { data: sources, error, isPending } = useQuery(sourcesQuery(projectId))
  const hash = useLocation({ select: (location) => location.hash })

  // The sidebar's link arrives before the list: scroll once it is there.
  useEffect(() => {
    if (!sources || !hash.startsWith('source-')) return
    document.getElementById(hash)?.scrollIntoView?.({ block: 'start' })
  }, [sources, hash])

  return (
    <SettingsSection title="Data sources" description="This project’s data sources. Agents can register more over MCP.">
      {isPending ? (
        <Loading what="data sources" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The data sources cannot be loaded:" />
      ) : (
        <>
          {sources.length === 0 ? (
            <p className="text-sm text-muted-foreground">No data sources yet.</p>
          ) : (
            <ul aria-label="Data sources" className="divide-y rounded-lg border">
              {sources.map((source) => (
                <SourceItem key={source.id} projectId={projectId} source={source} marked={hash === `source-${source.id}`} />
              ))}
            </ul>
          )}
          <AddSource projectId={projectId} />
        </>
      )}
    </SettingsSection>
  )
}

function SourceItem({ projectId, source, marked }: { projectId: Id; source: DataSource; marked: boolean }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const refresh = useMutation({
    mutationFn: () => refreshSource(source.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.sources(projectId) }),
  })
  const watch = useMutation({
    mutationFn: () => (source.monitor_id ? unwatchSource(source.id) : watchSource(source.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.sources(projectId) }),
  })
  const watched = !!source.monitor_id
  // Context.dev watches pages and files on the web, not uploads.
  const watchable = watched || /^https?:\/\//.test(source.address)
  return (
    <li
      id={`source-${source.id}`}
      aria-label={source.name}
      data-marked={marked || undefined}
      className="flex scroll-mt-4 flex-col gap-1 px-4 py-3 text-sm data-marked:bg-muted/50"
    >
      {editing ? (
        <SourceForm projectId={projectId} source={source} onDone={() => setEditing(false)} />
      ) : (
        <>
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{source.name}</span>
                {watched && <Badge variant="secondary">Watched</Badge>}
              </span>
              <span className="text-xs text-muted-foreground">
                {accessLabels[source.access_kind]} · {formatLabels[source.format]}
              </span>
            </div>
            <div className="flex shrink-0 gap-1">
              <IconButton
                label={`Refresh ${source.name} now`}
                disabled={refresh.isPending}
                onClick={() => refresh.mutate()}
              >
                <RefreshCw className={refresh.isPending ? 'animate-spin' : undefined} />
              </IconButton>
              {watchable && (
                <IconButton
                  label={watched ? `Stop watching ${source.name}` : `Watch ${source.name}`}
                  disabled={watch.isPending}
                  onClick={() => watch.mutate()}
                >
                  {watched ? <EyeOff /> : <Eye />}
                </IconButton>
              )}
              <IconButton label={`Edit ${source.name}`} onClick={() => setEditing(true)}>
                <Pencil />
              </IconButton>
            </div>
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground" title={source.address}>
            {source.address}
          </p>
          <p className="text-xs text-muted-foreground">
            Refresh: {describeFreshness(source.freshness)}
            <WatchInterval source={source} />
            {source.last_checked_at && (
              <>
                {' · '}last checked <LiveTime value={source.last_checked_at} />
              </>
            )}
          </p>
          {source.provenance && <SourceProvenance provenance={source.provenance} />}
          {source.last_error && (
            <p className="flex items-start gap-1 text-xs text-amber-800 dark:text-amber-300">
              <CircleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
              Last refresh failed: {source.last_error}. Widgets on it show stale data.
            </p>
          )}
          {refresh.isSuccess && (
            <p role="status" className="text-xs text-muted-foreground">
              Refresh queued; the list updates when it is done.
            </p>
          )}
          {refresh.error && <ErrorNotice error={refresh.error} prefix="Not refreshed:" />}
          {watch.error && <ErrorNotice error={watch.error} prefix={watched ? 'Not unwatched:' : 'Not watched:'} />}
        </>
      )}
    </li>
  )
}

function AddSource({ projectId }: { projectId: Id }) {
  const [open, setOpen] = useState<'source' | 'upload' | null>(null)
  if (!open)
    return (
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => setOpen('source')}>
          <Plus aria-hidden="true" />
          Add data source
        </Button>
        <Button variant="outline" onClick={() => setOpen('upload')}>
          <FileUp aria-hidden="true" />
          Upload a PDF
        </Button>
      </div>
    )
  return (
    <div className="max-w-xl rounded-lg border p-4">
      {open === 'source' ? (
        <SourceForm projectId={projectId} onDone={() => setOpen(null)} />
      ) : (
        <UploadPdf projectId={projectId} onDone={() => setOpen(null)} />
      )}
    </div>
  )
}

type Engine = 'pdfplumber' | 'context.dev'
type Extract = 'pages' | 'tables'

/**
 * A PDF nobody hosts: posted as the body of `POST /projects/{id}/files`, then registered
 * as a document source on the address that answers, read by the chosen engine.
 */
function UploadPdf({ projectId, onDone }: { projectId: Id; onDone: () => void }) {
  const queryClient = useQueryClient()
  const web = useQuery(webSettingsQuery())
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [engine, setEngine] = useState<Engine>('pdfplumber')
  const [extract, setExtract] = useState<Extract>('pages')

  const upload = useMutation({
    mutationFn: async (chosen: File) => {
      const stored = await uploadFile(projectId, chosen)
      return registerSource(projectId, {
        name: name.trim(),
        access_kind: 'document',
        format: 'pdf',
        address: stored.address,
        options: { engine, extract },
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.sources(projectId) })
      onDone()
    },
  })

  const choose = (chosen: File | null) => {
    setFile(chosen)
    // The file's name, until one is typed.
    if (chosen && name.trim() === '') setName(chosen.name.replace(/\.pdf$/i, ''))
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (file && name.trim() !== '' && !upload.isPending) upload.mutate(file)
  }

  return (
    <form onSubmit={onSubmit} aria-label="Upload a PDF" className="flex flex-col gap-3">
      <h3 className="font-semibold">Upload a PDF</h3>
      <Field label="PDF file" hint="Up to 50 MiB. The same file uploaded twice is stored once.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="file"
            accept="application/pdf,.pdf"
            aria-describedby={describedBy}
            onChange={(event) => choose(event.target.files?.[0] ?? null)}
          />
        )}
      </Field>
      <Field label="Name">
        {({ id }) => <Input id={id} value={name} required onChange={(event) => setName(event.target.value)} />}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Engine"
          hint={
            engine === 'context.dev' && web.data && !web.data.context_dev_configured
              ? 'No Context.dev key is configured: reading it will fail.'
              : undefined
          }
        >
          {({ id, describedBy }) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className={selectClass}
              value={engine}
              onChange={(event) => setEngine(event.target.value as Engine)}
            >
              <option value="pdfplumber">Local (pdfplumber)</option>
              <option value="context.dev">Context.dev (better tables, OCR)</option>
            </select>
          )}
        </Field>
        <Field label="Extract">
          {({ id }) => (
            <select id={id} className={selectClass} value={extract} onChange={(event) => setExtract(event.target.value as Extract)}>
              <option value="pages">Pages: the text of each page</option>
              <option value="tables">Tables: the rows of each table</option>
            </select>
          )}
        </Field>
      </div>
      {upload.error && <ErrorNotice error={upload.error} prefix="Not added:" />}
      <div className="flex gap-2">
        <Button type="submit" disabled={upload.isPending || !file || name.trim() === ''}>
          {upload.isPending ? 'Uploading…' : 'Upload and add'}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** Minutes as typed, to seconds; empty is none. */
function seconds(minutes: string): number | null {
  const value = Number(minutes)
  return minutes.trim() === '' || !Number.isFinite(value) ? null : Math.round(value * 60)
}

/**
 * A new source, or a change to one. The access kind and the format are fixed once a
 * source is registered; a changed address makes the backend refresh it.
 */
function SourceForm({ projectId, source, onDone }: { projectId: Id; source?: DataSource; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(source?.name ?? '')
  const [accessKind, setAccessKind] = useState<AccessKind>(source?.access_kind ?? 'url')
  const [address, setAddress] = useState(source?.address ?? '')
  const [format, setFormat] = useState<DataFormat>(source?.format ?? 'csv')
  const [freshnessKind, setFreshnessKind] = useState<FreshnessKind>(source?.freshness.kind ?? 'manual')
  const [ttlMinutes, setTtlMinutes] = useState(
    source?.freshness.ttl_seconds ? String(source.freshness.ttl_seconds / 60) : '',
  )
  const [conflict, setConflict] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () => {
      setConflict(null)
      const freshness: FreshnessPolicy = {
        kind: freshnessKind,
        ttl_seconds: freshnessKind === 'ttl' ? seconds(ttlMinutes) : null,
        latest_period_ttl_seconds: source?.freshness.latest_period_ttl_seconds ?? null,
      }
      const fields = { name: name.trim(), address: address.trim(), freshness }
      return source
        ? updateSource(source, fields)
        : registerSource(projectId, { ...fields, access_kind: accessKind, format })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.sources(projectId) })
      onDone()
    },
    onError: async (error) => {
      if (!isConflict(error) || !source) return
      // The list is read again, so the next save carries the latest revision.
      await queryClient.invalidateQueries({ queryKey: keys.sources(projectId) })
      setConflict(
        'Someone else changed this source while you were editing; it has been read again. ' +
          'Your changes were not saved; save again to replace it.',
      )
    },
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() !== '' && address.trim() !== '' && !save.isPending) save.mutate()
  }

  return (
    <form
      onSubmit={onSubmit}
      aria-label={source ? `Edit ${source.name}` : 'New data source'}
      className="flex flex-col gap-3"
    >
      <h3 className="font-semibold">{source ? `Edit ${source.name}` : 'New data source'}</h3>
      <Field label="Name">
        {({ id }) => <Input id={id} value={name} required onChange={(event) => setName(event.target.value)} />}
      </Field>
      {source ? (
        <p className="text-xs text-muted-foreground">
          {accessLabels[source.access_kind]} · {formatLabels[source.format]}: the access kind and format stay as
          registered.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Access kind">
            {({ id }) => (
              <select
                id={id}
                className={selectClass}
                value={accessKind}
                onChange={(event) => setAccessKind(event.target.value as AccessKind)}
              >
                {Object.entries(accessLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Format">
            {({ id }) => (
              <select id={id} className={selectClass} value={format} onChange={(event) => setFormat(event.target.value as DataFormat)}>
                {Object.entries(formatLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
      )}
      <Field label="Address" hint="A URL, or where the document lives.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            value={address}
            required
            className="font-mono"
            onChange={(event) => setAddress(event.target.value)}
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Refresh">
          {({ id }) => (
            <select
              id={id}
              className={selectClass}
              value={freshnessKind}
              onChange={(event) => setFreshnessKind(event.target.value as FreshnessKind)}
            >
              {Object.entries(freshnessLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        {freshnessKind === 'ttl' && (
          <Field label="Fresh for (minutes)">
            {({ id }) => (
              <Input
                id={id}
                type="number"
                min={1}
                required
                value={ttlMinutes}
                onChange={(event) => setTtlMinutes(event.target.value)}
              />
            )}
          </Field>
        )}
      </div>
      {conflict && <ConflictNotice message={conflict} />}
      {save.error && !isConflict(save.error) && (
        <ErrorNotice error={save.error} prefix={source ? 'Not saved:' : 'Not added:'} />
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || name.trim() === '' || address.trim() === ''}>
          {source ? 'Save' : 'Add data source'}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
