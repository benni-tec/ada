import { Check, Pencil, X } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

import { Input } from '@/components/ui/input'

import { IconButton } from './icon-action'
import { ConflictNotice } from './notices'

/**
 * A heading that can be renamed in place: a pencil beside it opens the editor, Enter saves
 * and Escape cancels. Saving goes through a revision check; after a conflict the editor
 * stays open with the person's text, next to what the record is now.
 */
export function EditableTitle({
  value,
  label,
  save,
  pending,
  conflict,
  error,
  reset,
}: {
  value: string
  /** What is being renamed, e.g. "session title". */
  label: string
  save: (value: string) => Promise<unknown>
  pending: boolean
  conflict: string | null
  error: string | null
  reset: () => void
}) {
  const inputId = useId()
  const [draft, setDraft] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (draft === null || draft.trim() === '') return
    try {
      await save(draft.trim())
      setDraft(null)
    } catch {
      // Shown through `conflict` or `error`; keep the draft for another try.
    }
  }

  const cancel = () => {
    setDraft(null)
    reset()
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {draft === null ? (
        <div className="flex min-w-0 items-center gap-1">
          <h1 className="min-w-0 text-2xl font-semibold break-words">{value}</h1>
          <IconButton label="Rename" onClick={() => setDraft(value)} className="text-muted-foreground">
            <Pencil />
          </IconButton>
        </div>
      ) : (
        <form onSubmit={submit} className="flex min-w-0 items-center gap-1">
          <label htmlFor={inputId} className="sr-only">
            New {label}
          </label>
          <Input
            id={inputId}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                // Only the editor closes, not a dialog around it.
                event.stopPropagation()
                cancel()
              }
            }}
            autoFocus
            className="h-9 min-w-0 flex-1 text-lg font-semibold md:text-lg"
          />
          <IconButton label="Save" type="submit" disabled={pending || draft.trim() === ''}>
            <Check />
          </IconButton>
          <IconButton label="Cancel" onClick={cancel}>
            <X />
          </IconButton>
        </form>
      )}
      {conflict && <ConflictNotice message={conflict} onDismiss={reset} />}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
