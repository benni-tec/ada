import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'

import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiFailure,
  agentSettingsQuery,
  keys,
  projectQuery,
  setAgentInstructions,
  setProjectInstructions,
  settingsKeys,
  type Id,
} from '@/lib/api'

import { Field, SettingsSection } from './form'

/** What the briefing reads of each text; the rest is cut (docs/contracts.md, "The agent"). */
export const MAX_INSTRUCTIONS = 20_000

const CONFLICT =
  'Someone else changed these instructions while you were editing; they have been read again. ' +
  'Your text is kept; save again to replace theirs.'

/** The session agent's instructions for every project, saved with the settings' revision. */
export function GlobalInstructionsSection() {
  const queryClient = useQueryClient()
  const { data: settings, error, isPending } = useQuery(agentSettingsQuery())
  return (
    <SettingsSection
      title="Agent instructions"
      description="Shared by all projects: what the session agent is told in every project, after ADA’s own rules, which always hold. For example a skill to paste."
    >
      {isPending ? (
        <Loading what="the agent settings" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The agent settings cannot be loaded:" />
      ) : (
        <InstructionsForm
          label="Instructions for every project"
          stored={settings.instructions}
          save={async (text) => {
            const view = await setAgentInstructions(text, settings.revision)
            queryClient.setQueryData(settingsKeys.agent(), view)
          }}
          reload={() => queryClient.invalidateQueries({ queryKey: settingsKeys.agent() })}
        />
      )}
    </SettingsSection>
  )
}

/** The session agent's instructions for this project, saved with the project's revision. */
export function ProjectInstructionsSection({ projectId, projectName }: { projectId: Id; projectName?: string }) {
  const queryClient = useQueryClient()
  const { data: project, error, isPending } = useQuery(projectQuery(projectId))
  return (
    <SettingsSection
      title="Agent instructions"
      description={
        <>
          For {projectName ? <strong>{projectName}</strong> : 'this project'} only: what the session agent is told here,
          after ADA’s rules and the instructions for every project. For example the challenge it is about, the language
          to answer in, or what to cite.
        </>
      }
    >
      {isPending ? (
        <Loading what="the project" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The project cannot be loaded:" />
      ) : (
        <InstructionsForm
          label="Instructions for this project"
          stored={project.agent_instructions}
          save={async (text) => {
            const saved = await setProjectInstructions(projectId, text, project.revision)
            queryClient.setQueryData(keys.project(projectId), saved)
            await queryClient.invalidateQueries({ queryKey: keys.projects(), exact: true })
          }}
          reload={() => queryClient.invalidateQueries({ queryKey: keys.project(projectId), exact: true })}
        />
      )}
    </SettingsSection>
  )
}

/**
 * A textarea over stored instructions. What is typed is kept apart from what is stored
 * (`draft`), so a conflict reads the record again without losing the text.
 */
function InstructionsForm({
  label,
  stored,
  save,
  reload,
}: {
  label: string
  stored: string
  save: (text: string) => Promise<void>
  reload: () => Promise<unknown>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const text = draft ?? stored
  const mutation = useMutation({
    mutationFn: () => {
      setConflict(false)
      return save(text)
    },
    onSuccess: () => setDraft(null),
    onError: async (error) => {
      if (!(error instanceof ApiFailure && error.isConflict)) return
      await reload()
      setConflict(true)
    },
  })
  const changed = draft !== null && draft !== stored

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!mutation.isPending) mutation.mutate()
  }

  let hint: ReactNode = `${text.length.toLocaleString('en')} characters; the agent reads up to ${MAX_INSTRUCTIONS.toLocaleString('en')}.`
  if (text.length > MAX_INSTRUCTIONS)
    hint = (
      <span className="text-amber-800 dark:text-amber-300">
        {text.length.toLocaleString('en')} characters: the agent reads only the first{' '}
        {MAX_INSTRUCTIONS.toLocaleString('en')}.
      </span>
    )

  return (
    <form onSubmit={onSubmit} aria-label={label} className="flex flex-col gap-3">
      <Field label={label} hint={hint}>
        {({ id, describedBy }) => (
          <Textarea
            id={id}
            aria-describedby={describedBy}
            value={text}
            onChange={(event) => setDraft(event.target.value)}
            className="max-h-[60svh] min-h-48 font-mono text-xs md:text-xs"
          />
        )}
      </Field>
      {conflict && <ConflictNotice message={CONFLICT} />}
      {mutation.error && !(mutation.error instanceof ApiFailure && mutation.error.isConflict) && (
        <ErrorNotice error={mutation.error} prefix="Not saved:" />
      )}
      {mutation.isSuccess && !changed && (
        <p role="status" className="text-xs text-muted-foreground">
          Saved; the next message uses them.
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={mutation.isPending || (!changed && !conflict)}>
          Save
        </Button>
        {changed && (
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>
            Discard changes
          </Button>
        )}
      </div>
    </form>
  )
}
