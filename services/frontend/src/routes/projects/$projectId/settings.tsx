import { createFileRoute, redirect } from '@tanstack/react-router'

// The settings are a modal over the project's pages now (`?settings=<section>`); the old
// address opens it over the overview, at the data sources when it names one.
export const Route = createFileRoute('/projects/$projectId/settings')({
  beforeLoad: ({ params, location }) => {
    const source = location.hash.startsWith('source-')
    throw redirect({
      to: '/projects/$projectId',
      params,
      search: { settings: source ? 'data-sources' : 'models' },
      hash: source ? location.hash : undefined,
      replace: true,
    })
  },
})
