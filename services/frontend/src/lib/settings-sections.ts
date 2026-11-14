// The sections of the settings modal (`?settings=<section>` on any project page), in the
// order of its side navigation: shared by all projects first, then this project's.

export const globalSections = {
  models: 'Models and providers',
  'agent-instructions': 'Agent instructions',
  web: 'Web',
} as const

export const projectSections = {
  'data-sources': 'Data sources',
  'project-instructions': 'Agent instructions',
} as const

export type SettingsSectionId = keyof typeof globalSections | keyof typeof projectSections

/** The section the gear opens. */
export const defaultSettingsSection: SettingsSectionId = 'models'

export function isSettingsSection(value: unknown): value is SettingsSectionId {
  return typeof value === 'string' && (Object.hasOwn(globalSections, value) || Object.hasOwn(projectSections, value))
}

/** Adds `?settings=<section>` to the current page's search, for a link to that section. */
export const withSettings =
  (section: SettingsSectionId) =>
  (previous: Record<string, unknown>): Record<string, unknown> => ({ ...previous, settings: section })
