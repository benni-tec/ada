import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { SystemStatus } from '@/components/system-status'
import { ThemeToggle } from '@/components/theme-toggle'
import { AdaMark, Vahti } from '@/components/vahti/vahti'
import { createProject, keys, projectsQuery } from '@/lib/api'

export const Route = createFileRoute('/')({
  component: Projects,
})

function Projects() {
  const { data: projects, error, isPending } = useQuery(projectsQuery())

  return (
    <div className="min-h-svh">
      <header className="flex h-12 items-center gap-2 border-b px-4">
        <AdaMark size={26} />
        <span className="flex-1" />
        <ThemeToggle />
      </header>
      <main className="flex flex-col gap-8 p-4 md:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold">Projects</h1>
        <p className="mt-2 text-neutral-600 dark:text-neutral-400">
          Each project holds its data sources, the sessions that explore them and the widgets they produced.
        </p>
      </div>

      <CreateProject />

      <section aria-labelledby="project-list">
        <h2 id="project-list" className="sr-only">
          All projects
        </h2>
        {isPending ? (
          <Loading what="projects" />
        ) : error ? (
          <ErrorNotice error={error} prefix="The projects cannot be loaded:" />
        ) : projects.length === 0 ? (
          <div className="flex items-end gap-4">
            <Vahti pose="watching" size={88} label="" />
            <p className="pb-3 text-sm text-neutral-500">No projects yet. Create one above, or ask an agent to over MCP.</p>
          </div>
        ) : (
          <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
            {projects.map((project) => (
              <li key={project.id}>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: project.id }}
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-neutral-50 focus-visible:bg-neutral-50 dark:hover:bg-neutral-900 dark:focus-visible:bg-neutral-900"
                >
                  <span className="font-medium">{project.name}</span>
                  <span className="text-xs text-neutral-500">
                    Created <Time value={project.created_at} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="system-status" className="flex flex-col gap-2">
        <h2 id="system-status" className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
          System
        </h2>
        <SystemStatus />
      </section>
      </main>
    </div>
  )
}

function CreateProject() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inputId = useId()
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      setName('')
      await queryClient.invalidateQueries({ queryKey: keys.projects() })
      await navigate({ to: '/projects/$projectId', params: { projectId: project.id } })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() !== '') create.mutate(name.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-sm font-medium">
        New project
      </label>
      <div className="flex gap-2">
        <input
          id={inputId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Cancer screening in the Nordics"
          className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
        <button
          type="submit"
          disabled={create.isPending || name.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {create.isPending ? 'Creating…' : 'Create project'}
        </button>
      </div>
      {create.error && <ErrorNotice error={create.error} prefix="Not created:" />}
    </form>
  )
}
