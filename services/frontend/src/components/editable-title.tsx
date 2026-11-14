import { useId, useState, type FormEvent } from 'react'

import { ConflictNotice } from './notices'

/**
 * A heading that can be renamed in place. Saving goes through a revision check; after a
 * conflict the editor stays open with the person's text, next to what the record is now.
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
    <div className="flex flex-col gap-2">
      {draft === null ? (
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold break-words">{value}</h1>
          <button
            type="button"
            onClick={() => setDraft(value)}
            className="rounded text-sm text-neutral-600 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 dark:text-neutral-400"
          >
            Rename
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <label htmlFor={inputId} className="sr-only">
            New {label}
          </label>
          <input
            id={inputId}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => event.key === 'Escape' && cancel()}
            autoFocus
            className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-lg dark:border-neutral-700 dark:bg-neutral-900"
          />
          <button
            type="submit"
            disabled={pending || draft.trim() === ''}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            {pending ? 'Saving…' : 'Save'}
          </button>
          <button type="button" onClick={cancel} className="rounded-md px-3 py-1.5 text-sm">
            Cancel
          </button>
        </form>
      )}
      {conflict && <ConflictNotice message={conflict} onDismiss={reset} />}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
