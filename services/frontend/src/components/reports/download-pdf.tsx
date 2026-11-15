import { useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useState } from 'react'

import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { blocksOf, reportSourcesQuery, widgetIdsOf, widgetQuery, type Report, type ReportVersion } from '@/lib/api'

/**
 * Saves the version shown as a PDF, made in the browser (components/reports/report-pdf,
 * loaded on the first click): its widgets drawn at the version's run, each with a link back
 * into ADA on this host. Says how far it got while the widgets are drawn.
 */
export function DownloadPdf({ report, version }: { report: Report; version: ReportVersion }) {
  const queryClient = useQueryClient()
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [error, setError] = useState<Error | null>(null)

  const download = async () => {
    setError(null)
    setProgress({ done: 0, total: 0 })
    try {
      const ids = widgetIdsOf(blocksOf(version))
      const [{ downloadReportPdf }, sources, widgets] = await Promise.all([
        import('./report-pdf'),
        queryClient.fetchQuery(reportSourcesQuery(version.id)),
        Promise.all(ids.map((id) => queryClient.fetchQuery(widgetQuery(id)))),
      ])
      await downloadReportPdf(
        { report, version, sources, widgets: new Map(widgets.map((widget) => [widget.id, widget])), origin: window.location.origin },
        (done, total) => setProgress({ done, total }),
      )
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error(String(failure)))
    } finally {
      setProgress(null)
    }
  }

  const label = !progress
    ? 'Download PDF'
    : progress.total > 0 && progress.done < progress.total
      ? `Drawing widget ${progress.done + 1} of ${progress.total}…`
      : 'Making the PDF…'
  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" onClick={() => void download()} disabled={progress !== null} aria-live="polite">
        <Download data-icon="inline-start" aria-hidden="true" />
        {label}
      </Button>
      {error && <ErrorNotice error={error} prefix="No PDF:" />}
    </div>
  )
}
