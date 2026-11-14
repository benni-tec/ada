import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { defaultRehypePlugins, Streamdown, type Components, type ExtraProps } from 'streamdown'

import { specText } from '@/lib/columns'
import { canOpenPipeline, fetchAll, MAIN_INPUT, openPipeline, type InputResult } from '@/lib/host'
import { Flags, ValueFlags, type Loaded } from '@/lib/runtime'

import { inputsOf, parse, resolve, type Piece, type Placeholder, type Resolved } from './model'

// Each placeholder goes into the Markdown as a marker of private-use characters, which no
// Markdown syntax touches, and comes out of the parsed tree as an element of its own. The
// values never pass through the Markdown: React writes them as text. A marker says whether
// it is a value or a table, so the plugin needs nothing else: streamdown caches its
// processor, plugins included, across renders.
const VALUE = '\uE000'
const TABLE = '\uE001'
const END = '\uE002'
const MARKER = new RegExp(`([${VALUE}${TABLE}])(\\d+)${END}`, 'g')
const VALUE_TAG = 'ada-placeholder'
const TABLE_TAG = 'ada-placeholder-table'

const marker = (placeholder: Placeholder, index: number) =>
  `${placeholder.column === undefined ? TABLE : VALUE}${index}${END}`

/** The part of a hast node this file reads and writes. */
type Node = {
  type: string
  tagName?: string
  value?: string
  properties?: Record<string, unknown>
  children?: Node[]
}

const isTable = (node: Node) => node.type === 'element' && node.tagName === TABLE_TAG
const isBlank = (node: Node) => node.type === 'text' && !node.value?.trim()

function split(text: string, inLink: boolean): Node[] {
  const nodes: Node[] = []
  let last = 0
  for (const match of text.matchAll(MARKER)) {
    if (match.index > last) nodes.push({ type: 'text', value: text.slice(last, match.index) })
    nodes.push({
      type: 'element',
      tagName: match[1] === TABLE ? TABLE_TAG : VALUE_TAG,
      properties: { dataIndex: Number(match[2]), dataInLink: inLink },
      children: [],
    })
    last = match.index + match[0].length
  }
  if (last < text.length) nodes.push({ type: 'text', value: text.slice(last) })
  return nodes
}

/** A table cannot sit in a paragraph: the paragraph becomes the parts around it. */
function lift(paragraph: Node): Node[] {
  const parts: Node[] = []
  let run: Node[] = []
  const flush = () => {
    if (run.some((node) => !isBlank(node))) parts.push({ ...paragraph, children: run })
    run = []
  }
  for (const child of paragraph.children ?? []) {
    if (isTable(child)) {
      flush()
      parts.push(child)
    } else {
      run.push(child)
    }
  }
  flush()
  return parts
}

function walk(node: Node, inLink: boolean) {
  // Code keeps its markers; the code components write them back as typed.
  if (!node.children || node.tagName === 'code' || node.tagName === 'pre') return
  const link = inLink || node.tagName === 'a'
  const children: Node[] = []
  for (const child of node.children) {
    if (child.type === 'text' && child.value && MARKER.test(child.value)) {
      MARKER.lastIndex = 0
      children.push(...split(child.value, link))
      continue
    }
    walk(child, link)
    if (child.type === 'element' && child.tagName === 'p' && child.children?.some(isTable)) children.push(...lift(child))
    else children.push(child)
  }
  node.children = children
}

/** A rehype plugin that turns the markers into placeholder elements: `{{input}}` as a
 * block (a paragraph around it is split), the others inline. It runs after sanitising,
 * which would drop these elements. */
const placeholderElements = () => (tree: Node) => walk(tree, false)

/** The Markdown with a marker for each placeholder, numbered in order. */
function withMarkers(pieces: readonly Piece[]): string {
  let source = ''
  let index = 0
  for (const piece of pieces) source += typeof piece === 'string' ? piece : marker(piece, index++)
  return source
}

/** Code with its markers written back as the placeholders were typed. */
function restore(children: ReactNode, placeholders: readonly Placeholder[]): ReactNode {
  if (typeof children === 'string') {
    return children.replace(MARKER, (_, _kind: string, index: string) => placeholders[Number(index)]?.source ?? '')
  }
  if (Array.isArray(children)) return children.map((child) => restore(child, placeholders))
  return children
}

/** "13:02:11", for the tooltip. */
const time = (date: Date) => date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/** What the tooltip says: where the value comes from, and why it is missing. */
function describe(placeholder: Placeholder, resolved: Resolved, result: InputResult | undefined): string {
  const lines = [
    resolved.kind === 'missing' ? resolved.reason : null,
    `Input: ${placeholder.input}`,
    placeholder.column !== undefined ? `Column: ${placeholder.column}` : null,
    placeholder.where.length > 0
      ? `Row: ${placeholder.where.map((filter) => `${filter.column} = ${filter.value}`).join(' and ')}`
      : null,
    placeholder.format ? `Format: ${placeholder.format}` : null,
  ]
  if (result?.status === 'loaded') {
    lines.push(`Run: ${result.data.run_id}`, `Fetched: ${time(result.fetchedAt)}`)
    if (result.data.is_scenario) lines.push('Scenario: simulated numbers')
    if (result.data.is_stale) lines.push('Stale: last good data, a refresh failed')
  }
  if (canOpenPipeline()) lines.push('Click to open its pipeline')
  return lines.filter(Boolean).join('\n')
}

/** A value, or "no value": a button to the input's pipeline, or plain inside a link. */
function Value({
  placeholder,
  result,
  inLink,
}: {
  placeholder: Placeholder
  result: InputResult | undefined
  inLink: boolean
}) {
  const resolved = resolve(placeholder, result)
  const title = describe(placeholder, resolved, result)
  const content: ReactNode =
    resolved.kind === 'value' ? (
      resolved.text
    ) : resolved.kind === 'missing' ? (
      resolved.label
    ) : (
      // A table where only a value fits (e.g. in a heading): its size instead.
      `${resolved.total} rows`
    )
  const flags = result?.status === 'loaded' && <ValueFlags data={result.data} />
  const props = {
    className: 'ada-placeholder',
    title,
    'data-missing': resolved.kind === 'missing' || undefined,
    'data-numeric': (resolved.kind === 'value' && resolved.numeric) || undefined,
  }
  if (inLink || !canOpenPipeline()) {
    return (
      <span {...props}>
        {content}
        {flags}
      </span>
    )
  }
  return (
    <button type="button" {...props} onClick={() => openPipeline(placeholder.input)}>
      {content}
      {flags}
    </button>
  )
}

/** `{{input}}`: the input as a compact table, with a line naming it under it. */
function Table({ placeholder, result }: { placeholder: Placeholder; result: InputResult | undefined }) {
  const resolved = resolve(placeholder, result)
  if (resolved.kind !== 'table') return <Value placeholder={placeholder} result={result} inLink={false} />
  const title = describe(placeholder, resolved, result)
  const shown = resolved.rows.length
  const note = `Input ${placeholder.input}: ${resolved.more ? `the first ${shown} rows` : `${shown} ${shown === 1 ? 'row' : 'rows'}`}`
  return (
    <figure className="ada-text-table">
      <div className="ada-text-table-scroll">
        <table className="ada-table">
          <thead>
            <tr>
              {resolved.columns.map((column, index) => (
                <th key={column.name} scope="col" className={resolved.numeric[index] ? 'ada-numeric' : undefined}>
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {resolved.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) => (
                  <td key={resolved.columns[index].name} className={resolved.numeric[index] ? 'ada-numeric' : undefined}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <figcaption className="ada-note">
        {canOpenPipeline() ? (
          <button type="button" className="ada-placeholder" title={title} onClick={() => openPipeline(placeholder.input)}>
            {note}
          </button>
        ) : (
          <span title={title}>{note}</span>
        )}
        {result?.status === 'loaded' && <ValueFlags data={result.data} />}
      </figcaption>
    </figure>
  )
}

// Streamdown's sanitising and link hardening, without its raw HTML: Markdown's HTML is
// written as text, never parsed.
const REHYPE_PLUGINS = [defaultRehypePlugins.sanitize, defaultRehypePlugins.harden, placeholderElements]

type Rendered = { node?: Node } & ExtraProps

const indexOf = (props: Rendered) => Number(props.node?.properties?.dataIndex)

/**
 * Markdown with figures from the widget's inputs.
 *
 * Spec: `markdown`, CommonMark with GFM tables, in which `{{input.column}}`,
 * `{{input.column:format}}`, `{{input.column[column=value]}}` and `{{input}}` show values
 * of the widget's inputs (see model.ts); `\{{` writes `{{`. Every input it names is read
 * in the view's run. No raw HTML and no images; links open in a new tab.
 */
export function Text({ widget, data, fetchedAt }: Loaded) {
  const markdown = specText(widget.spec, 'markdown') ?? ''
  const pieces = useMemo(() => parse(markdown), [markdown])
  const placeholders = useMemo(() => pieces.filter((piece): piece is Placeholder => typeof piece !== 'string'), [pieces])
  const others = useMemo(() => inputsOf(pieces).filter((name) => name !== MAIN_INPUT), [pieces])

  // The runtime read main, which fixed the run; the other inputs read that run.
  const key = `${widget.id} ${data.run_id} ${others.join(' ')}`
  const [read, setRead] = useState<{ key: string; results: Map<string, InputResult> } | null>(null)
  useEffect(() => {
    if (others.length === 0) return
    let current = true
    void fetchAll(widget.id, data.run_id, others).then((results) => current && setRead({ key, results }))
    return () => {
      current = false
    }
  }, [key, widget.id, data.run_id, others])

  const results = useMemo(() => {
    const all = new Map<string, InputResult>([[MAIN_INPUT, { input: MAIN_INPUT, status: 'loaded', data, fetchedAt }]])
    if (read?.key === key) for (const [name, result] of read.results) all.set(name, result)
    return all
  }, [data, fetchedAt, read, key])

  const source = useMemo(() => withMarkers(pieces), [pieces])

  const components = useMemo<Components>(
    () => ({
      [VALUE_TAG]: (props: Rendered) => {
        const placeholder = placeholders[indexOf(props)]
        return (
          <Value
            placeholder={placeholder}
            result={results.get(placeholder.input)}
            inLink={props.node?.properties?.dataInLink === true}
          />
        )
      },
      [TABLE_TAG]: (props: Rendered) => {
        const placeholder = placeholders[indexOf(props)]
        return <Table placeholder={placeholder} result={results.get(placeholder.input)} />
      },
      a: ({ href, children }) => (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ),
      img: () => null,
      // Plain code, without the chat's highlighter, header and copy button.
      pre: ({ children }) => <pre>{children}</pre>,
      code: ({ children }) => <code>{restore(children, placeholders)}</code>,
      inlineCode: ({ children }) => <code>{restore(children, placeholders)}</code>,
      table: ({ children }) => (
        <div className="ada-text-table-scroll">
          <table className="ada-table">{children}</table>
        </div>
      ),
    }),
    [placeholders, results],
  )

  if (others.length > 0 && read?.key !== key) {
    return (
      <div className="ada-centered" role="status">
        <span className="ada-muted">Loading…</span>
      </div>
    )
  }

  // The runtime marks main; an other input that is stale is marked here as well.
  const staleElsewhere =
    !data.is_stale && others.some((name) => {
      const result = results.get(name)
      return result?.status === 'loaded' && result.data.is_stale
    })

  return (
    <>
      {staleElsewhere && <Flags data={{ is_scenario: false, is_stale: true }} />}
      <div className="ada-text">
        <Streamdown
          mode="static"
          parseIncompleteMarkdown={false}
          controls={false}
          skipHtml
          disallowedElements={['img']}
          rehypePlugins={REHYPE_PLUGINS}
          components={components}
        >
          {source}
        </Streamdown>
      </div>
    </>
  )
}
