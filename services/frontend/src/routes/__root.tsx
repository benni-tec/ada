import type { QueryClient } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { TriangleAlert } from 'lucide-react'

import { TooltipProvider } from '@/components/ui/tooltip'
import { ThemeProvider } from '@/lib/theme'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
})

// Tests render whole routes; the devtools would only add noise to them.
const devtools = import.meta.env.MODE !== 'test'

/** The providers every page shares; each layout below draws its own frame. */
function RootLayout() {
  return (
    <ThemeProvider>
      {/* A short delay, so moving the pointer across a row of icons does not flash a tooltip each. */}
      <TooltipProvider delayDuration={300}>
        <DataRuleBanner />
        <Outlet />
        {devtools && <ReactQueryDevtools buttonPosition="bottom-left" />}
        {devtools && <TanStackRouterDevtools position="bottom-right" />}
      </TooltipProvider>
    </ThemeProvider>
  )
}

/** The platform is not for patient data: a bar on every page says so, and it never goes
 * away. Models are evaluated on synthetic profiles only. */
function DataRuleBanner() {
  return (
    <div role="note" className="flex items-center justify-center gap-2 bg-red-700 px-4 py-1.5 text-center text-sm font-medium text-white">
      <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
      <span>Educational use only. Do not enter patient data.</span>
    </div>
  )
}
