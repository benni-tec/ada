import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Pencil, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { IconButton } from '@/components/icon-action'
import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  addModel,
  agentKeys,
  agentSettingsQuery,
  ApiFailure,
  createProvider,
  deleteModel,
  deleteProvider,
  setResearchAgent,
  setSessionAgent,
  settingsKeys,
  updateProvider,
  type AgentSettings,
  type LlmModel,
  type LlmProvider,
  type ProviderKind,
} from '@/lib/api'

import { Field, selectClass, SettingsSection } from './form'

const kindLabels: Record<ProviderKind, string> = {
  'openai-compatible': 'OpenAI-compatible',
  gemini: 'Gemini',
}

const isConflict = (error: unknown) => error instanceof ApiFailure && error.isConflict

/** The settings, and the models list the composers read, after a change. */
function useReload() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: settingsKeys.agent() }),
      queryClient.invalidateQueries({ queryKey: agentKeys.models() }),
    ])
}

/**
 * The agent for every project: the providers with their keys, their models, and the one
 * model that answers in sessions. Keys go in and never come back out: the page only learns
 * whether one is stored.
 */
export function AgentSettingsSection() {
  const { data: settings, error, isPending } = useQuery(agentSettingsQuery())
  return (
    <SettingsSection
      title="Models and providers"
      description="Shared by all projects: the providers and their keys, their models, and the model that answers in sessions."
    >
      {isPending ? (
        <Loading what="the agent settings" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The agent settings cannot be loaded:" />
      ) : (
        <>
          {!settings.secrets_available && (
            <div
              role="note"
              className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
            >
              <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <p>
                <code className="font-mono">ADA_SECRET_KEY</code> is not set, so API keys cannot be stored. Providers
                without a key still work; set it on the backend and restart it to add keys.
              </p>
            </div>
          )}
          <AgentPicker
            settings={settings}
            label="Session agent"
            hint="The model that answers in every project’s sessions. A message can still ask for another one in the composer."
            none="None: nobody answers in sessions"
            value={settings.session_agent}
            set={setSessionAgent}
          />
          <AgentPicker
            settings={settings}
            label="Research agent"
            hint="The model that works on a brief handed to it from a session, in a session of its own, and reports back."
            none="Use the session agent"
            value={settings.research_agent}
            set={setResearchAgent}
          />
          <div className="flex flex-col gap-3">
            <h3 className="text-base font-semibold">Providers</h3>
            {settings.providers.length === 0 && (
              <p className="text-sm text-muted-foreground">No providers yet. Add one to give sessions an agent.</p>
            )}
            {settings.providers.length > 0 && (
              <ul className="grid gap-3 lg:grid-cols-2">
                {settings.providers.map((provider) => (
                  <ProviderCard
                    key={provider.id}
                    provider={provider}
                    models={settings.models.models.filter((model) => model.provider === provider.name)}
                    secretsAvailable={settings.secrets_available}
                  />
                ))}
              </ul>
            )}
            <AddProvider secretsAvailable={settings.secrets_available} />
          </div>
        </>
      )}
    </SettingsSection>
  )
}

/** Which model fills one role; a change is saved at once. */
function AgentPicker({
  settings,
  label,
  hint,
  none,
  value,
  set,
}: {
  settings: AgentSettings
  label: string
  hint: string
  none: string
  value: string | null | undefined
  set: (modelId: string | null, revision: number) => Promise<AgentSettings>
}) {
  const reload = useReload()
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (modelId: string | null) => {
      setConflict(null)
      return set(modelId, settings.revision)
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(settingsKeys.agent(), saved)
      await queryClient.invalidateQueries({ queryKey: agentKeys.models() })
    },
    onError: async (error) => {
      if (!isConflict(error)) return
      await reload()
      setConflict('Someone else changed the agent settings meanwhile; they are shown as they are now. Choose again.')
    },
  })
  const models = settings.models.models
  return (
    <div className="flex max-w-xl flex-col gap-2">
      <Field
        label={label}
        hint={hint}
      >
        {({ id, describedBy }) => (
          <select
            id={id}
            aria-describedby={describedBy}
            className={selectClass}
            value={value ?? ''}
            disabled={save.isPending}
            onChange={(event) => save.mutate(event.target.value === '' ? null : event.target.value)}
          >
            <option value="">{none}</option>
            {models.map((model) => (
              <option key={model.id} value={model.id} disabled={!model.available}>
                {model.available ? model.id : `${model.id} (unavailable: ${model.reason ?? 'unknown reason'})`}
              </option>
            ))}
          </select>
        )}
      </Field>
      {conflict && <ConflictNotice message={conflict} onDismiss={() => setConflict(null)} />}
      {save.error && !isConflict(save.error) && <ErrorNotice error={save.error} prefix="Not saved:" />}
    </div>
  )
}

function KeyStatus({ provider }: { provider: LlmProvider }) {
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <KeyRound aria-hidden="true" className="size-3.5" />
      {provider.has_api_key ? 'Key stored' : 'No key'}
    </span>
  )
}

/** A provider: what it is, whether its key is stored, and its models. */
function ProviderCard({
  provider,
  models,
  secretsAvailable,
}: {
  provider: LlmProvider
  models: LlmModel[]
  secretsAvailable: boolean
}) {
  const reload = useReload()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({ mutationFn: () => deleteProvider(provider.id), onSuccess: reload })

  return (
    <li aria-label={`Provider ${provider.name}`} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      {editing ? (
        <ProviderForm
          provider={provider}
          secretsAvailable={secretsAvailable}
          onDone={() => setEditing(false)}
        />
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="font-semibold">{provider.name}</h4>
              <Badge variant="secondary">{kindLabels[provider.kind]}</Badge>
            </div>
            {provider.base_url && (
              <p className="truncate font-mono text-xs text-muted-foreground" title={provider.base_url}>
                {provider.base_url}
              </p>
            )}
            <KeyStatus provider={provider} />
          </div>
          <div className="flex shrink-0 gap-1">
            <IconButton label={`Edit ${provider.name}`} onClick={() => setEditing(true)}>
              <Pencil />
            </IconButton>
            <IconButton label={`Delete ${provider.name}`} onClick={() => setConfirming(true)}>
              <Trash2 />
            </IconButton>
          </div>
        </div>
      )}
      {confirming && (
        <div role="group" aria-label={`Delete ${provider.name}?`} className="flex flex-col gap-2 rounded-md border border-destructive/40 p-3 text-sm">
          <p>
            Delete {provider.name} and its {models.length === 1 ? 'model' : `${models.length} models`}? If one of them is
            the session agent, sessions have no agent until another is picked.
          </p>
          <div className="flex gap-2">
            <Button variant="destructive" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
              Delete
            </Button>
            <Button variant="outline" size="sm" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
          {remove.error && <ErrorNotice error={remove.error} prefix="Not deleted:" />}
        </div>
      )}
      <Models provider={provider} models={models} />
    </li>
  )
}

function Models({ provider, models }: { provider: LlmProvider; models: LlmModel[] }) {
  const reload = useReload()
  const [name, setName] = useState('')
  const add = useMutation({
    mutationFn: (model: string) => addModel(provider.id, model),
    onSuccess: async () => {
      setName('')
      await reload()
    },
  })
  const remove = useMutation({ mutationFn: deleteModel, onSuccess: reload })
  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() !== '' && !add.isPending) add.mutate(name.trim())
  }
  return (
    <div className="flex flex-col gap-2">
      <h5 className="text-xs font-medium text-muted-foreground">Models</h5>
      {models.length === 0 ? (
        <p className="text-xs text-muted-foreground">No models yet.</p>
      ) : (
        <ul aria-label={`Models of ${provider.name}`} className="divide-y rounded-md border">
          {models.map((model) => (
            <li key={model.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm">
              <span className="flex min-w-0 flex-col">
                <span className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs">{model.model}</span>
                  {model.purposes.includes('session_agent') && <Badge variant="outline">Session agent</Badge>}
                  {model.purposes.includes('research_agent') && <Badge variant="outline">Research agent</Badge>}
                </span>
                {!model.available && (
                  <span className="text-xs text-amber-800 dark:text-amber-300">Unavailable: {model.reason}</span>
                )}
              </span>
              <IconButton label={`Delete ${model.id}`} disabled={remove.isPending} onClick={() => remove.mutate(model.id)}>
                <Trash2 />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      {remove.error && <ErrorNotice error={remove.error} prefix="Not deleted:" />}
      <form onSubmit={onSubmit} aria-label={`Add a model to ${provider.name}`} className="flex items-end gap-2">
        <div className="flex-1">
          <Field label="Model name">
            {({ id }) => (
              <Input id={id} value={name} placeholder="e.g. gemini-2.5-flash" onChange={(event) => setName(event.target.value)} />
            )}
          </Field>
        </div>
        <Button type="submit" variant="outline" disabled={add.isPending || name.trim() === ''}>
          <Plus aria-hidden="true" />
          Add model
        </Button>
      </form>
      {add.error && <ErrorNotice error={add.error} prefix="Not added:" />}
    </div>
  )
}

function AddProvider({ secretsAvailable }: { secretsAvailable: boolean }) {
  const [open, setOpen] = useState(false)
  if (!open)
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        <Plus aria-hidden="true" />
        Add provider
      </Button>
    )
  return (
    <div className="max-w-xl rounded-lg border p-4">
      <ProviderForm secretsAvailable={secretsAvailable} onDone={() => setOpen(false)} />
    </div>
  )
}

/**
 * A new provider, or a change to one. The key field is a password field that always starts
 * empty: in a change, empty keeps the stored key, and "Remove the stored key" clears it.
 */
function ProviderForm({
  provider,
  secretsAvailable,
  onDone,
}: {
  provider?: LlmProvider
  secretsAvailable: boolean
  onDone: () => void
}) {
  const reload = useReload()
  const [name, setName] = useState(provider?.name ?? '')
  const [kind, setKind] = useState<ProviderKind>(provider?.kind ?? 'gemini')
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [conflict, setConflict] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () => {
      setConflict(null)
      const base_url = baseUrl.trim() === '' ? null : baseUrl.trim()
      const key = apiKey === '' ? {} : { api_key: apiKey }
      if (!provider) return createProvider({ name: name.trim(), kind, base_url, ...key })
      return updateProvider(provider.id, {
        expected_revision: provider.revision,
        name: name.trim(),
        kind,
        base_url,
        ...(clearKey ? { api_key: null } : key),
      })
    },
    onSuccess: async () => {
      setApiKey('')
      await reload()
      onDone()
    },
    onError: async (error) => {
      setApiKey('')
      if (!isConflict(error) || !provider) return
      await reload()
      setConflict(
        'Someone else changed this provider while you were editing; it now holds their version. ' +
          'Your changes were not saved; save again to replace it.',
      )
    },
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() !== '' && !save.isPending) save.mutate()
  }

  const keyHint = !secretsAvailable
    ? 'Keys cannot be stored: ADA_SECRET_KEY is not set.'
    : provider?.has_api_key
      ? 'A key is stored. Leave this empty to keep it.'
      : kind === 'gemini'
        ? 'Gemini needs a key.'
        : 'Optional: a local server may need none.'

  return (
    <form
      onSubmit={onSubmit}
      aria-label={provider ? `Edit ${provider.name}` : 'New provider'}
      className="flex flex-col gap-3"
      autoComplete="off"
    >
      <h4 className="font-semibold">{provider ? `Edit ${provider.name}` : 'New provider'}</h4>
      <Field label="Name" hint="Lowercase letters, digits and dashes; the first half of its models’ ids.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            value={name}
            required
            pattern="[a-z0-9-]+"
            placeholder="e.g. gemini"
            onChange={(event) => setName(event.target.value)}
          />
        )}
      </Field>
      <Field label="Kind">
        {({ id }) => (
          <select id={id} className={selectClass} value={kind} onChange={(event) => setKind(event.target.value as ProviderKind)}>
            {Object.entries(kindLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Base URL" hint="For an OpenAI-compatible server, e.g. http://localhost:8001/v1. Empty: the provider’s default.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            type="url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        )}
      </Field>
      <Field label="API key" hint={keyHint}>
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            type="password"
            autoComplete="new-password"
            value={apiKey}
            disabled={!secretsAvailable || clearKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        )}
      </Field>
      {provider?.has_api_key && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} />
          Remove the stored key
        </label>
      )}
      {conflict && <ConflictNotice message={conflict} />}
      {save.error && !isConflict(save.error) && (
        <ErrorNotice error={save.error} prefix={provider ? 'Not saved:' : 'Not added:'} />
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || name.trim() === ''}>
          {provider ? 'Save' : 'Add provider'}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
