import type { QueryClient } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
})

// Tests render whole routes; the devtools would only add noise to them.
const devtools = import.meta.env.MODE !== 'test'

function RootLayout() {
  return (
    <div className="min-h-svh bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <header className="border-b border-neutral-200 dark:border-neutral-800">
        <div className="mx-auto flex h-14 max-w-7xl items-center px-4">
          <Link to="/" className="text-lg font-semibold">
            ADA
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">
        <Outlet />
      </main>
      {devtools && <ReactQueryDevtools buttonPosition="bottom-left" />}
      {devtools && <TanStackRouterDevtools position="bottom-right" />}
    </div>
  )
}
