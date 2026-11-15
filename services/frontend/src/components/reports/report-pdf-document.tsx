import interBold from '@expo-google-fonts/inter/700Bold/Inter_700Bold.ttf?url'
import interRegular from '@expo-google-fonts/inter/400Regular/Inter_400Regular.ttf?url'
import { Document, Font, Image, Link, Page, StyleSheet, Text, View } from '@react-pdf/renderer'

import {
  blocksOf,
  describeTimeRange,
  widgetIdsOf,
  type Block,
  type CalloutBlock,
  type Id,
  type Report,
  type ReportSource,
  type ReportVersion,
  type Widget,
} from '@/lib/api'
import { citation, reportUrl } from '@/lib/report-pdf'
import type { WidgetSnapshot } from '@/lib/widgets'

// A report version as a PDF document: the blocks as text, each widget as a picture of
// itself at the version's run with the sources it reads (by their number in the list at
// the end), and one link back into ADA, on the host the PDF was made on.

/** A widget as the PDF shows it: its picture, or why there is none. */
export type Drawn = { widget: Widget; snapshot: WidgetSnapshot | null; error?: string }

export type PdfInput = {
  report: Report
  version: ReportVersion
  /** Every widget of the version, by id. */
  widgets: Map<Id, Widget>
  sources: ReportSource[]
  /** Where links lead: the host the PDF is made on. */
  origin: string
}

// A4 in points.
const A4_HEIGHT = 841.89

// Inter, served from this host: the PDF's built-in fonts have no Greek or mathematical
// signs (ρ, ≥), which reports use.
Font.register({ family: 'Inter', fonts: [{ src: interRegular }, { src: interBold, fontWeight: 700 }] })

const ink = '#171717'
const muted = '#525252'
const rule = '#d4d4d4'
const linkBlue = '#1d4ed8'
const tonesNote = '#0284c7'

const styles = StyleSheet.create({
  page: { paddingTop: 48, paddingBottom: 56, paddingHorizontal: 48, fontFamily: 'Inter', fontSize: 10.5, color: ink, lineHeight: 1.45 },
  kind: { fontSize: 9, color: muted, textTransform: 'uppercase', letterSpacing: 0.8 },
  title: { fontSize: 22, fontFamily: 'Inter', fontWeight: 700, lineHeight: 1.2, marginTop: 4, marginBottom: 8 },
  facts: { fontSize: 9, color: muted, marginBottom: 2 },
  link: { color: linkBlue, textDecoration: 'none' },
  header: { borderBottomWidth: 1, borderBottomColor: rule, paddingBottom: 12, marginBottom: 16 },
  h1: { fontSize: 16, lineHeight: 1.25, fontFamily: 'Inter', fontWeight: 700, marginTop: 10, marginBottom: 6 },
  h2: { fontSize: 13.5, lineHeight: 1.25, fontFamily: 'Inter', fontWeight: 700, marginTop: 8, marginBottom: 5 },
  h3: { fontSize: 11.5, lineHeight: 1.25, fontFamily: 'Inter', fontWeight: 700, marginTop: 6, marginBottom: 4 },
  paragraph: { marginBottom: 6 },
  callout: { borderLeftWidth: 3, paddingLeft: 10, paddingVertical: 6, marginBottom: 10 },
  inAda: { borderWidth: 1, borderColor: tonesNote, borderRadius: 4, paddingHorizontal: 12, paddingVertical: 8, marginTop: 16 },
  calloutLabel: { fontSize: 8.5, fontFamily: 'Inter', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, color: muted },
  figure: { marginVertical: 8, borderWidth: 1, borderColor: rule, borderRadius: 4 },
  picture: { width: '100%', objectFit: 'contain' },
  missing: { padding: 16, color: muted, fontSize: 9.5 },
  widgetFooter: { borderTopWidth: 1, borderTopColor: rule, paddingHorizontal: 8, paddingVertical: 5, fontSize: 8.5, color: muted },
  caption: { fontSize: 9.5, color: muted, marginTop: -4, marginBottom: 8 },
  sourcesTitle: { fontSize: 13.5, lineHeight: 1.25, fontFamily: 'Inter', fontWeight: 700, marginTop: 16, marginBottom: 6 },
  sourceList: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between' },
  source: { width: '48.5%', fontSize: 9, marginBottom: 5 },
  sourceName: { color: ink, textDecoration: 'none' },
  // From the top: placed by `bottom`, it lands at the top of some pages.
  pageFooter: { position: 'absolute', top: A4_HEIGHT - 36, left: 48, right: 48, fontSize: 8, color: muted, flexDirection: 'row', justifyContent: 'space-between' },
})

const tones: Record<CalloutBlock['tone'], { label: string; color: string }> = {
  note: { label: 'Note', color: tonesNote },
  finding: { label: 'Finding', color: '#059669' },
  warning: { label: 'Warning', color: '#d97706' },
}

export function ReportDocument({ report, version, sources: unordered, origin, drawn }: PdfInput & { drawn: Map<Id, Drawn> }) {
  const blocks = blocksOf(version)
  const sources = bibliography(unordered, widgetIdsOf(blocks))
  const made = new Date(version.created_at)
  return (
    <Document title={`${report.name} (version ${version.version})`} author="ADA" creator="ADA" producer="ADA">
      <Page size="A4" style={styles.page}>
        {/* First: a fixed element repeats from the page it is declared on. */}
        <View style={styles.pageFooter} fixed>
          <Text>
            {report.name} · version {version.version}
          </Text>
          <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
        </View>
        <View style={styles.header}>
          <Text style={styles.kind}>Report</Text>
          <Text style={styles.title}>{report.name}</Text>
          <Text style={styles.facts}>
            Version {version.version} · data period {describeTimeRange(version.time_range)} · made {made.toLocaleDateString()}
          </Text>
          <Text style={styles.facts}>Run {version.run_id}</Text>
        </View>
        {blocks.map((block, index) => (
          <BlockPdf key={index} block={block} depth={0} drawn={drawn} sources={sources} />
        ))}
        {sources.length > 0 && <Sources sources={sources} />}
        {/* Last, the one way back into ADA: on the version's page every widget opens at this
            run, with its pipeline and sources. */}
        <View style={styles.inAda} wrap={false}>
          <Text style={styles.calloutLabel}>In ADA</Text>
          <Link src={reportUrl(origin, report, version)} style={styles.link}>
            {reportUrl(origin, report, version)}
          </Link>
        </View>
      </Page>
    </Document>
  )
}

type Context = { drawn: Map<Id, Drawn>; sources: ReportSource[] }

/** The sources as a bibliography: numbered in the order the widgets first read them, then
 * any no widget names. A widget's footer cites them by number. */
function bibliography(sources: ReportSource[], widgetIds: Id[]): ReportSource[] {
  const first = (source: ReportSource) => {
    const at = widgetIds.findIndex((id) => source.widget_ids.includes(id))
    return at === -1 ? widgetIds.length : at
  }
  return sources.map((source, index) => ({ source, index })).sort((a, b) => first(a.source) - first(b.source) || a.index - b.index).map(({ source }) => source)
}

function BlockPdf({ block, depth, ...context }: { block: Block; depth: number } & Context) {
  switch (block.type) {
    case 'heading':
      return <Heading level={block.level}>{block.text}</Heading>
    case 'text':
      return <Paragraphs text={block.text} />
    case 'callout': {
      const tone = tones[block.tone] ?? tones.note
      return (
        <View style={[styles.callout, { borderLeftColor: tone.color }]} wrap={false}>
          <Text style={styles.calloutLabel}>{tone.label}</Text>
          {block.title && <Text style={{ fontWeight: 700 }}>{block.title}</Text>}
          <Paragraphs text={block.text} />
        </View>
      )
    }
    case 'widget':
      return <WidgetPdf id={block.widget_id} caption={block.caption} {...context} />
    case 'section':
      return (
        <View>
          {block.title && <Heading level={Math.min(depth + 2, 3) as 2 | 3}>{block.title}</Heading>}
          {block.blocks.map((child, index) => (
            <BlockPdf key={index} block={child} depth={depth + 1} {...context} />
          ))}
        </View>
      )
  }
}

function Heading({ level, children }: { level: 1 | 2 | 3; children: string }) {
  return <Text style={level === 1 ? styles.h1 : level === 2 ? styles.h2 : styles.h3}>{children}</Text>
}

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text.split(/\n\s*\n/).map((paragraph, index) => (
        <Text key={index} style={styles.paragraph}>
          {paragraph}
        </Text>
      ))}
    </>
  )
}

// The widest a picture is drawn, in points: A4's width less the margins.
const CONTENT_WIDTH = 595.28 - 2 * 48
// The tallest, so a figure and its footer fit on one page: a figure is never split, and
// one taller than a page cannot be laid out at all.
const MAX_PICTURE_HEIGHT = 520

function WidgetPdf({ id, caption, drawn, sources }: { id: Id; caption: string } & Context) {
  const entry = drawn.get(id)
  if (!entry) return <Text style={styles.missing}>Widget not available</Text>
  const { widget, snapshot, error } = entry
  const title = widget.title || 'Untitled widget'
  // A widget that drew nothing has no size to scale: no picture then.
  const drawnPicture = snapshot && snapshot.width > 0 && snapshot.height > 0 ? snapshot : null
  const height = drawnPicture ? Math.min(MAX_PICTURE_HEIGHT, (CONTENT_WIDTH * drawnPicture.height) / drawnPicture.width) : 0
  const cited = citation(sources.flatMap((source, index) => (source.widget_ids.includes(id) ? [index + 1] : [])))
  return (
    <>
      <View style={styles.figure} wrap={false}>
        {drawnPicture ? (
          <Image src={drawnPicture.image} style={[styles.picture, { height }]} />
        ) : (
          <Text style={styles.missing}>
            {title}: not drawn{error ? ` (${error})` : ''}
          </Text>
        )}
        <View style={styles.widgetFooter}>
          <Text>
            {title}
            {cited ? ` · Sources ${cited}` : ''}
          </Text>
        </View>
      </View>
      {caption && <Text style={styles.caption}>{caption}</Text>}
    </>
  )
}

/** The bibliography, in two columns: each source's number, its name (the link to where the
 * data came from) and when it was fetched; the addresses are behind the names. */
function Sources({ sources }: { sources: ReportSource[] }) {
  return (
    <View>
      <Text style={styles.sourcesTitle}>Sources</Text>
      <View style={styles.sourceList}>
        {sources.map((source, index) => (
          <View key={source.operator_id} style={styles.source} wrap={false}>
            <Text>
              [{index + 1}]{' '}
              {/^https?:\/\//i.test(source.address) ? (
                <Link src={source.address} style={styles.sourceName}>
                  {source.name}
                </Link>
              ) : (
                source.name
              )}
            </Text>
            {source.fetched_at && <Text style={{ color: muted }}>fetched {new Date(source.fetched_at).toLocaleString()}</Text>}
          </View>
        ))}
      </View>
    </View>
  )
}
