import { pdf, type DocumentProps } from '@react-pdf/renderer'
import { createElement, type ReactElement } from 'react'

import { blocksOf, widgetIdsOf, type Id } from '@/lib/api'
import { snapshotWidget } from '@/lib/widgets'

import { ReportDocument, type Drawn, type PdfInput } from './report-pdf-document'

// A report as a PDF, made in the browser; loaded only when someone downloads one.

/** Draws the version's widgets one after the other, telling `progress` how far it got, and
 * saves the PDF as "<report name> v<version>.pdf". */
export async function downloadReportPdf(input: PdfInput, progress: (done: number, total: number) => void) {
  const ids = widgetIdsOf(blocksOf(input.version))
  const drawn = new Map<Id, Drawn>()
  for (const [index, id] of ids.entries()) {
    progress(index, ids.length)
    const widget = input.widgets.get(id)
    if (!widget) continue
    try {
      drawn.set(id, { widget, snapshot: await snapshotWidget(widget, input.version.run_id) })
    } catch (error) {
      drawn.set(id, { widget, snapshot: null, error: error instanceof Error ? error.message : String(error) })
    }
  }
  progress(ids.length, ids.length)
  // ReportDocument renders a Document, which is what pdf() takes.
  const document_ = createElement(ReportDocument, { ...input, drawn }) as unknown as ReactElement<DocumentProps>
  const blob = await pdf(document_).toBlob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${fileName(input.report.name)} v${input.version.version}.pdf`
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

const fileName = (name: string) => name.replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim() || 'Report'
