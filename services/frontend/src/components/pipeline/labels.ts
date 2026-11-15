import type { Operator, OperatorKind, Roles } from '@/lib/api'

/** Where a source operator's data comes from, as far as the page knows it. */
export type SourceInfo = { name: string; address: string }

export const kindLabels: Record<OperatorKind, string> = {
  source: 'Source',
  history: 'History',
  extract: 'Extraction',
  input: 'Input',
  transform: 'SQL',
  statistic: 'Statistic',
  agent: 'Agent',
}

const MAX_NAME = 34

function shorten(text: string, max = MAX_NAME): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  if (flat.length <= max) return flat
  // At a word boundary when there is one close enough.
  const cut = flat.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return `${space > max / 2 ? cut.slice(0, space) : cut}…`
}

/**
 * The first meaningful words of a query: a leading comment says what the query is for in
 * the author's words, so it is preferred; otherwise the query itself, without comments.
 */
export function sqlHeadline(sql: string): string {
  const comment = /^\s*--\s*(.*\S)/.exec(sql)
  if (comment) return shorten(comment[1])
  const code = sql.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/--.*$/gm, ' ')
  return shorten(code) || 'Empty query'
}

function text(params: Record<string, unknown>, key: string): string {
  const value = params[key]
  return typeof value === 'string' ? value : ''
}

/** A node's name in a few words: the source's name, the query's first words, the slot. */
export function shortName(operator: Operator, source?: SourceInfo): string {
  const params = operator.params as Record<string, unknown>
  switch (operator.kind) {
    case 'source':
      return source?.name ?? 'A data source'
    case 'transform':
      return sqlHeadline(text(params, 'sql'))
    case 'input':
      return `Slot “${text(params, 'name')}”`
    case 'statistic':
      return shorten(text(params, 'tool')) || 'A statistic'
    case 'agent':
      return shorten(text(params, 'prompt')) || 'An agent step'
    case 'extract':
      return shorten(text(params, 'instruction')) || 'An extraction'
    case 'history': {
      const last = params.last
      return typeof last === 'number' ? `The last ${last} snapshots` : 'Earlier snapshots'
    }
  }
}

/** What each column means by the output's roles, e.g. "Measure" or "Lower bound of value". */
export function columnRoles(roles: Roles): Map<string, string[]> {
  const meanings = new Map<string, string[]>()
  const add = (column: string | null | undefined, meaning: string) => {
    if (column) meanings.set(column, [...(meanings.get(column) ?? []), meaning])
  }
  const { time, geo, measures = [] } = roles
  if (time) {
    const grain = time.grain ? ` (${time.grain})` : ''
    add(time.start, `Time: period start${grain}`)
    add(time.end, `Time: period end${grain}`)
  }
  if (geo) add(geo.code, `Geography: ${geo.system}, ${geo.level.replaceAll('_', ' ')}`)
  for (const measure of measures) {
    add(measure.value, 'Measure')
    add(measure.lower, `Lower bound of ${measure.value}`)
    add(measure.upper, `Upper bound of ${measure.value}`)
    add(measure.suppressed, `Suppression flag of ${measure.value}`)
    add(measure.coverage, `Coverage of ${measure.value}`)
  }
  return meanings
}
