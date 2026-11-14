import { errorMessage } from '@/lib/api'

/** A failed call, with the server's `detail` when it sent one. */
export function ErrorNotice({ error, prefix }: { error: unknown; prefix?: string }) {
  return (
    <p role="alert" className="text-sm text-red-700 dark:text-red-400">
      {prefix ? `${prefix} ` : ''}
      {errorMessage(error)}
    </p>
  )
}

/** Someone else changed a record while it was being edited here. */
export function ConflictNotice({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
    >
      <p>{message}</p>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="shrink-0 underline underline-offset-2">
          Dismiss
        </button>
      )}
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="text-sm text-neutral-500">
      Loading {what}…
    </p>
  )
}
