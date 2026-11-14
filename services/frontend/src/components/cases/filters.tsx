/** Pills that pick one view of a list, each with its count. */
export function Filters<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: readonly { value: T; label: string; count?: number }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(option.value)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? 'border-foreground font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {option.label}
            {option.count !== undefined && ` ${option.count}`}
          </button>
        )
      })}
    </div>
  )
}
