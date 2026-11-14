import type { QueryClient } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'

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
        <Outlet />
        {devtools && <ReactQueryDevtools buttonPosition="bottom-left" />}
        {devtools && <TanStackRouterDevtools position="bottom-right" />}
      </TooltipProvider>
    </ThemeProvider>
  )
}
