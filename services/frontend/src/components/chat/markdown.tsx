import { Streamdown } from 'streamdown'

import { cn } from '@/lib/utils'

/**
 * The agent's text as markdown, the way AI Elements' Response renders it: with streamdown,
 * which also draws text that is still arriving (an unclosed bold or code block) and
 * sanitises what it is given, so a model cannot put markup of its own on the page.
 */
export function Markdown({ children, streaming = false, className }: { children: string; streaming?: boolean; className?: string }) {
  return (
    <Streamdown
      isAnimating={streaming}
      className={cn('text-sm leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0', className)}
    >
      {children}
    </Streamdown>
  )
}
