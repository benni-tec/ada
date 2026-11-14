import { useId, useState, type ReactNode } from 'react'

/** The look of an icon action: the same square in light and dark mode. Disabled with
 * `aria-disabled` (so it stays focusable and its tooltip says why), it is dimmed and
 * does not react to the pointer. */
export const iconActionClass =
  'inline-flex size-7 items-center justify-center rounded-md text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 aria-expanded:bg-neutral-100 aria-expanded:text-neutral-900 aria-disabled:cursor-not-allowed aria-disabled:text-neutral-300 aria-disabled:hover:bg-transparent aria-disabled:hover:text-neutral-300 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100 dark:aria-expanded:bg-neutral-800 dark:aria-expanded:text-neutral-100 dark:aria-disabled:text-neutral-600 dark:aria-disabled:hover:bg-transparent dark:aria-disabled:hover:text-neutral-600'

/**
 * An icon-only control with a visible tooltip, which is also its accessible name
 * (`aria-labelledby`), so what a pointer, a keyboard and a screen reader get is the same
 * text. The tooltip shows on hover and on keyboard focus, and Escape hides it (WCAG 1.4.13).
 * It opens upwards and to the left: actions sit at the bottom right of a card, whose edges
 * clip anything outside.
 */
export function WithTooltip({ label, children }: { label: string; children: (labelledBy: string) => ReactNode }) {
  const id = useId()
  const [shown, setShown] = useState(false)
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShown(true)}
      onMouseLeave={() => setShown(false)}
      onFocus={(event) => setShown(focusVisible(event.target))}
      onBlur={() => setShown(false)}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && shown) {
          event.stopPropagation()
          setShown(false)
        }
      }}
    >
      {children(id)}
      <span
        id={id}
        role="tooltip"
        hidden={!shown}
        className="pointer-events-none absolute right-0 bottom-full z-10 mb-1.5 rounded bg-neutral-900 px-2 py-1 text-xs font-medium whitespace-nowrap text-white shadow dark:bg-neutral-100 dark:text-neutral-900"
      >
        {label}
      </span>
    </span>
  )
}

/** Focus from the keyboard rather than a click; a click is hovering anyway. */
function focusVisible(element: Element): boolean {
  try {
    return element.matches(':focus-visible')
  } catch {
    // An engine without the selector (jsdom): show it.
    return true
  }
}

const iconProps = {
  width: 16,
  height: 16,
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const

/** Three tiles of a dashboard and a plus in the fourth. */
export function AddToDashboardIcon() {
  return (
    <svg {...iconProps}>
      <rect x="1.75" y="1.75" width="5" height="5" rx="1" />
      <rect x="9.25" y="1.75" width="5" height="5" rx="1" />
      <rect x="1.75" y="9.25" width="5" height="5" rx="1" />
      <path d="M11.75 9.25v5M9.25 11.75h5" />
    </svg>
  )
}

/** A speech bubble: the conversation the widget came from. */
export function SessionIcon() {
  return (
    <svg {...iconProps}>
      <path d="M2.25 3.75a1.5 1.5 0 0 1 1.5-1.5h8.5a1.5 1.5 0 0 1 1.5 1.5v5.5a1.5 1.5 0 0 1-1.5 1.5H7l-3 2.75v-2.75h-.25a1.5 1.5 0 0 1-1.5-1.5z" />
      <path d="M5.25 5.5h5.5M5.25 7.75h3.5" />
    </svg>
  )
}
