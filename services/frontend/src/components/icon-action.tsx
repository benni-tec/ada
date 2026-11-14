import type { ComponentProps, ReactElement, ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * A tooltip on a control: shown on hover and on keyboard focus, hidden by Escape (WCAG
 * 1.4.13), which is what shadcn's Tooltip does. The control names itself (`aria-label`)
 * with the same words, so a pointer, a keyboard and a screen reader all get one text.
 */
export function Hint({
  label,
  children,
  side = 'top',
}: {
  label: ReactNode
  /** One element that takes a ref: a button or a link. */
  children: ReactElement
  side?: ComponentProps<typeof TooltipContent>['side']
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{label}</TooltipContent>
    </Tooltip>
  )
}

/**
 * An icon-only button with its tooltip, which is also its accessible name. Disabled with
 * `aria-disabled` rather than `disabled` when `reason` is given: it stays focusable, so
 * the keyboard reaches the tooltip saying why.
 */
export function IconButton({
  label,
  children,
  side,
  variant = 'ghost',
  size = 'icon-sm',
  unavailable,
  onClick,
  className,
  ...props
}: Omit<ComponentProps<typeof Button>, 'aria-label' | 'children'> & {
  label: string
  /** The icon. */
  children: ReactNode
  side?: ComponentProps<typeof TooltipContent>['side']
  /** Shown instead of `label` when the action cannot be used now, and why. */
  unavailable?: string
}) {
  return (
    <Hint label={unavailable ?? label} side={side}>
      <Button
        type="button"
        variant={variant}
        size={size}
        aria-label={unavailable ?? label}
        aria-disabled={unavailable ? true : undefined}
        onClick={unavailable ? undefined : onClick}
        {...props}
        className={cn('aria-disabled:cursor-not-allowed aria-disabled:opacity-50', className)}
      >
        {children}
      </Button>
    </Hint>
  )
}
