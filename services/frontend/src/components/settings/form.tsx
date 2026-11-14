import { useId, type ReactNode } from 'react'

/** A native select that looks like shadcn's Input. */
export const selectClass =
  'h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 py-1 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30'

/** A labelled field, with a hint below that the control is described by. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  /** Renders the control with the ids it needs. */
  children: (ids: { id: string; describedBy: string | undefined }) => ReactNode
}) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children({ id, describedBy: hint ? hintId : undefined })}
      {hint && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}

/** One part of the settings page, with its heading and a line saying what it covers. */
export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string
  description: ReactNode
  children: ReactNode
}) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}
