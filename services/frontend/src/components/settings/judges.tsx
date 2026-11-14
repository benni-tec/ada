import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'

import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { OutcomeLabel } from '@/components/verdict-badge'
import {
  ApiFailure,
  judgeDefaultsQuery,
  judgeKeys,
  judgeKinds,
  modelsQuery,
  overrideProjectJudge,
  projectInstructions,
  projectJudgesQuery,
  setJudgeDefaults,
  strictnesses,
  verdictsQuery,
  type Id,
  type JudgeDefaults,
  type JudgeField,
  type JudgeKind,
  type JudgeSettings,
  type LlmModel,
  type Strictness,
} from '@/lib/api'
import { withSettings } from '@/lib/settings-sections'

import { Field, selectClass, SettingsSection } from './form'

/** What the backend keeps of a judge's instructions. */
const MAX_INSTRUCTIONS = 20_000

const CONFLICT =
  'Someone else changed this judge while you were editing; it is shown as it is now. ' +
  'Your changes are kept; save again to replace theirs.'

const isConflict = (error: unknown) => error instanceof ApiFailure && error.isConflict

/** A change to send: the fields edited, and for a project null where it inherits again. */
type Change = { strictness?: Strictness | null; model_id?: string | null; instructions?: string | null }

/** The global defaults: one card per kind. */
export function GlobalJudgesSection() {
  const queryClient = useQueryClient()
  const defaults = useQuery(judgeDefaultsQuery())
  const models = useQuery(modelsQuery())
  const reload = () => queryClient.invalidateQueries({ queryKey: judgeKeys.defaults() })
  return (
    <SettingsSection
      title="Judges"
      description="Shared by all projects: a judge is one of the configured models. It reviews what agents write into widgets, the figures in text widgets and the data in custom widgets’ code, against the widgets’ inputs. Each project may override these."
    >
      {defaults.isPending ? (
        <Loading what="the judges" />
      ) : defaults.error ? (
        <ErrorNotice error={defaults.error} prefix="The judges cannot be loaded:" />
      ) : (
        judgeKinds.map(({ kind, label, about }) => {
          const current = defaults.data.find((entry) => entry.kind === kind)
          if (!current) return null
          return (
            <JudgeCard
              key={kind}
              label={label}
              about={about}
              values={current}
              models={models.data?.models}
              save={async (change) => {
                const saved = await setJudgeDefaults(kind, { ...change, expected_revision: current.revision })
                queryClient.setQueryData(judgeKeys.defaults(), (old: JudgeDefaults[] | undefined) =>
                  old?.map((entry) => (entry.kind === kind ? saved : entry)),
                )
                await queryClient.invalidateQueries({ queryKey: ['projects'], predicate: isJudgesQuery })
              }}
              reload={reload}
            />
          )
        })
      )}
    </SettingsSection>
  )
}

// Every project's effective settings follow the defaults.
const isJudgesQuery = (query: { queryKey: readonly unknown[] }) => query.queryKey[2] === 'judges'

/** This project's judges: the effective values, which fields it overrides, and its verdicts. */
export function ProjectJudgesSection({ projectId, projectName }: { projectId: Id; projectName?: string }) {
  const queryClient = useQueryClient()
  const effective = useQuery(projectJudgesQuery(projectId))
  const defaults = useQuery(judgeDefaultsQuery())
  const models = useQuery(modelsQuery())
  const reload = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: judgeKeys.project(projectId) }),
      queryClient.invalidateQueries({ queryKey: judgeKeys.defaults() }),
    ])
  const error = effective.error ?? defaults.error
  return (
    <SettingsSection
      title="Judges"
      description={
        <>
          For {projectName ? <strong>{projectName}</strong> : 'this project'} only: each field follows the global default
          (Global › Judges) until it is set here. The project’s instructions are added after the global ones.
        </>
      }
    >
      {effective.isPending || defaults.isPending ? (
        <Loading what="the judges" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The judges cannot be loaded:" />
      ) : (
        judgeKinds.map(({ kind, label, about }) => {
          const current = effective.data?.find((entry) => entry.kind === kind)
          const global = defaults.data?.find((entry) => entry.kind === kind)
          if (!current) return null
          const send = async (change: Change) => {
            const saved = await overrideProjectJudge(projectId, kind, { ...change, expected_revision: current.revision })
            queryClient.setQueryData(judgeKeys.project(projectId), (old: JudgeSettings[] | undefined) =>
              old?.map((entry) => (entry.kind === kind ? saved : entry)),
            )
          }
          return (
            <JudgeCard
              key={kind}
              label={label}
              about={about}
              values={{ ...current, instructions: projectInstructions(current, global) }}
              project={{
                overridden: new Set(current.overridden as JudgeField[]),
                globalInstructions: global?.instructions.trim() ?? '',
                inherit: (field) => send({ [field]: null }),
              }}
              models={models.data?.models}
              save={send}
              reload={reload}
            >
              <RecentVerdicts projectId={projectId} kind={kind} />
            </JudgeCard>
          )
        })
      )}
    </SettingsSection>
  )
}

/**
 * One kind's settings: strictness, model and instructions, saved together with the
 * revision they were read at. What is typed is kept apart from what is stored (`drafts`),
 * so a conflict reads the record again without losing it. For a project, each field says
 * whether it is the global default or set here, and can go back to the default.
 */
function JudgeCard({
  label,
  about,
  values,
  project,
  models,
  save,
  reload,
  children,
}: {
  label: string
  about: string
  values: { strictness: Strictness; model_id?: string | null; instructions: string }
  project?: {
    overridden: Set<JudgeField>
    globalInstructions: string
    inherit: (field: JudgeField) => Promise<void>
  }
  models: readonly LlmModel[] | undefined
  save: (change: Change) => Promise<void>
  reload: () => Promise<unknown>
  children?: ReactNode
}) {
  const headingId = useId()
  const [drafts, setDrafts] = useState<Change>({})
  const [conflict, setConflict] = useState(false)
  const stored = { strictness: values.strictness, model_id: values.model_id ?? null, instructions: values.instructions }
  const shown = { ...stored, ...drafts } as typeof stored
  const changes = Object.fromEntries(
    Object.entries(drafts).filter(([field, value]) => value !== stored[field as JudgeField]),
  ) as Change
  const changed = Object.keys(changes).length > 0
  const edit = (change: Change) => setDrafts((previous) => ({ ...previous, ...change }))

  const onError = async (error: Error) => {
    if (!isConflict(error)) return
    await reload()
    setConflict(true)
  }
  const mutation = useMutation({
    mutationFn: () => {
      setConflict(false)
      return save(changes)
    },
    onSuccess: () => setDrafts({}),
    onError,
  })
  const inherit = useMutation({
    mutationFn: (field: JudgeField) => {
      setConflict(false)
      return project!.inherit(field)
    },
    onSuccess: (_, field) =>
      setDrafts((previous) => {
        const rest = { ...previous }
        delete rest[field]
        return rest
      }),
    onError,
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!mutation.isPending && changed) mutation.mutate()
  }

  /** Where a project's field comes from, and the way back to the default. */
  const origin = (field: JudgeField, name: string) => {
    if (!project) return null
    if (!project.overridden.has(field)) return <p className="text-xs text-muted-foreground">Global default</p>
    return (
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Set for this project
        <Button
          type="button"
          variant="link"
          size="xs"
          className="h-auto p-0"
          aria-label={`Use global default for ${name}`}
          disabled={inherit.isPending}
          onClick={() => inherit.mutate(field)}
        >
          Use global default
        </Button>
      </p>
    )
  }

  const noModels = models !== undefined && models.length === 0
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 rounded-lg border p-4">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} className="text-base font-semibold">
          {label}
        </h3>
        <p className="text-sm text-muted-foreground">{about}</p>
      </div>
      <form onSubmit={onSubmit} aria-label={`${label} judge`} className="flex flex-col gap-4">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium">Strictness</legend>
          {strictnesses.map(({ value, label: name, does }) => (
            <label key={value} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name={`${headingId}-strictness`}
                value={value}
                checked={shown.strictness === value}
                onChange={() => edit({ strictness: value })}
                className="mt-1"
              />
              <span>
                <span className="font-medium">{name}</span>
                <span className="text-muted-foreground"> · {does}</span>
              </span>
            </label>
          ))}
          {origin('strictness', 'the strictness')}
        </fieldset>

        <div className="flex max-w-xl flex-col gap-1">
          <Field
            label="Model"
            hint={
              noModels ? (
                <>
                  No models are configured.{' '}
                  <Link to="." search={withSettings('models')} replace resetScroll={false} className="underline underline-offset-2">
                    Add one in Global › Models and providers
                  </Link>
                  .
                </>
              ) : (
                'The configured model that reviews. Without one nothing is reviewed.'
              )
            }
          >
            {({ id, describedBy }) => (
              <select
                id={id}
                aria-describedby={describedBy}
                className={selectClass}
                value={shown.model_id ?? ''}
                onChange={(event) => edit({ model_id: event.target.value === '' ? null : event.target.value })}
              >
                {/* A project inherits by "Use global default", so "none" is only the global choice. */}
                <option value="" disabled={Boolean(project) && shown.model_id !== null}>
                  {project ? 'No model: nothing is reviewed' : 'None: nothing is reviewed'}
                </option>
                {shown.model_id && !models?.some((model) => model.id === shown.model_id) && (
                  <option value={shown.model_id}>{shown.model_id}</option>
                )}
                {models?.map((model) => (
                  <option key={model.id} value={model.id} disabled={!model.available}>
                    {model.available ? model.id : `${model.id} (unavailable: ${model.reason ?? 'unknown reason'})`}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {origin('model_id', 'the model')}
        </div>

        <div className="flex flex-col gap-1">
          {project && project.globalInstructions && (
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium">Global instructions</p>
              <p className="rounded-md bg-muted px-3 py-2 font-mono text-xs whitespace-pre-wrap">{project.globalInstructions}</p>
            </div>
          )}
          <Field
            label={project ? 'Instructions for this project' : 'Instructions'}
            hint={
              project
                ? 'Added to the judge’s prompt after the global instructions.'
                : `Added to the judge’s prompt in every project. ${shown.instructions.length.toLocaleString('en')} of ${MAX_INSTRUCTIONS.toLocaleString('en')} characters.`
            }
          >
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                value={shown.instructions}
                maxLength={MAX_INSTRUCTIONS}
                onChange={(event) => edit({ instructions: event.target.value })}
                className="min-h-24 font-mono text-xs md:text-xs"
              />
            )}
          </Field>
          {origin('instructions', 'the instructions')}
        </div>

        {conflict && <ConflictNotice message={CONFLICT} />}
        {mutation.error && !isConflict(mutation.error) && <ErrorNotice error={mutation.error} prefix="Not saved:" />}
        {inherit.error && !isConflict(inherit.error) && <ErrorNotice error={inherit.error} prefix="Not saved:" />}
        {mutation.isSuccess && !changed && (
          <p role="status" className="text-xs text-muted-foreground">
            Saved; the next review uses it.
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" disabled={mutation.isPending || !changed}>
            Save
          </Button>
          {changed && (
            <Button type="button" variant="outline" onClick={() => setDrafts({})}>
              Discard changes
            </Button>
          )}
        </div>
      </form>
      {children}
    </section>
  )
}

/** The kind's latest verdicts in the project, each linking to its widget. */
function RecentVerdicts({ projectId, kind }: { projectId: Id; kind: JudgeKind }) {
  const headingId = useId()
  const { data: widgets, error, isPending } = useQuery(verdictsQuery(projectId, kind))
  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <h4 id={headingId} className="text-sm font-medium">
        Recent verdicts
      </h4>
      {isPending ? (
        <Loading what="the verdicts" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The verdicts cannot be loaded:" />
      ) : widgets.length === 0 ? (
        <p className="text-sm text-muted-foreground">No widget has been reviewed yet.</p>
      ) : (
        <ul aria-labelledby={headingId} className="flex flex-col divide-y text-sm">
          {widgets.slice(0, 10).map((widget) => (
            <li key={widget.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
              <Link
                to="/projects/$projectId/widgets/$widgetId"
                params={{ projectId, widgetId: widget.id }}
                className="min-w-0 flex-1 truncate font-medium underline-offset-2 hover:underline"
              >
                {widget.title || 'Untitled widget'}
              </Link>
              <OutcomeLabel verdict={widget.verdict} />
              {widget.verdict && (
                <span className="text-xs text-muted-foreground">
                  <Time value={widget.verdict.checked_at} />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
