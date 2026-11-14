import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useId } from 'react'

import { Modal } from '@/components/modal'
import { projectQuery, type Id } from '@/lib/api'
import { globalSections, projectSections, withSettings, type SettingsSectionId } from '@/lib/settings-sections'
import { cn } from '@/lib/utils'

import { AgentSettingsSection } from './agents'
import { DataSourcesSection } from './data-sources'
import { GlobalInstructionsSection, ProjectInstructionsSection } from './instructions'
import { WebSection } from './web'

/**
 * The settings named by `?settings=<section>`, in a large modal over whatever page is
 * beneath: a side navigation in two groups (shared by all projects, this project's) and
 * the chosen section. Escape and × drop the parameter and leave the page as it was.
 */
export function SettingsModal({ projectId }: { projectId: Id }) {
  const { settings } = useSearch({ strict: false })
  if (!settings) return null
  return <OpenSettings projectId={projectId} section={settings} />
}

function OpenSettings({ projectId, section }: { projectId: Id; section: SettingsSectionId }) {
  const navigate = useNavigate()
  const project = useQuery(projectQuery(projectId))

  const close = () =>
    void navigate({
      to: '.',
      search: (previous: Record<string, unknown>) => ({ ...previous, settings: undefined }),
      replace: true,
      resetScroll: false,
    })

  return (
    <Modal title="Settings" onClose={close}>
      <div className="flex h-full min-h-0 flex-col sm:flex-row">
        <nav aria-label="Settings sections" className="flex shrink-0 flex-col gap-4 border-b p-3 sm:w-60 sm:border-r sm:border-b-0">
          <NavGroup title="Global" note="Shared by all projects" sections={globalSections} current={section} />
          <NavGroup title="This project" note={project.data?.name ?? ''} sections={projectSections} current={section} />
        </nav>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          <div className="flex max-w-4xl flex-col gap-6">
            <Section section={section} projectId={projectId} projectName={project.data?.name} />
          </div>
        </div>
      </div>
    </Modal>
  )
}

function NavGroup({
  title,
  note,
  sections,
  current,
}: {
  title: string
  note: string
  sections: Partial<Record<SettingsSectionId, string>>
  current: SettingsSectionId
}) {
  const headingId = useId()
  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-col gap-1">
      <div className="px-2">
        <h3 id={headingId} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {title}
        </h3>
        {note && <p className="truncate text-xs text-muted-foreground">{note}</p>}
      </div>
      <ul className="flex flex-col gap-0.5">
        {Object.entries(sections).map(([id, label]) => {
          const active = id === current
          return (
            <li key={id}>
              <Link
                to="."
                search={withSettings(id as SettingsSectionId)}
                replace
                resetScroll={false}
                aria-current={active ? 'page' : undefined}
                data-active={active || undefined}
                className={cn(
                  'block rounded-md px-2 py-1.5 text-sm hover:bg-muted',
                  active && 'bg-muted font-medium text-foreground',
                )}
              >
                {label}
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Section({ section, projectId, projectName }: { section: SettingsSectionId; projectId: Id; projectName?: string }) {
  switch (section) {
    case 'models':
      return <AgentSettingsSection />
    case 'agent-instructions':
      return <GlobalInstructionsSection />
    case 'web':
      return <WebSection />
    case 'data-sources':
      return <DataSourcesSection projectId={projectId} />
    case 'project-instructions':
      return <ProjectInstructionsSection projectId={projectId} projectName={projectName} />
  }
}
