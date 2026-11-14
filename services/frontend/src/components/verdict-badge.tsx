import { useMutation, useQueryClient } from '@tanstack/react-query'
import { OctagonX, RefreshCw, TriangleAlert, type LucideIcon } from 'lucide-react'
import { useState } from 'react'

import { Hint } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Time } from '@/components/provenance'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { judgeKeys, keys, reviewWidget, type Finding, type Id, type Verdict, type Widget } from '@/lib/api'
import { cn } from '@/lib/utils'
import { verdictSummary } from '@/lib/verdicts'

/** The verdict's words and icon, inline (the judges' settings list them so). */
export function OutcomeLabel({ verdict }: { verdict: Verdict | null | undefined }) {
  const { label, Icon, className } = verdictSummary(verdict)
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', className)}>
      <Icon aria-hidden="true" className="size-3.5" />
      {label}
    </span>
  )
}

const severities: { severity: Finding['severity']; label: string; Icon: LucideIcon; className: string }[] = [
  { severity: 'error', label: 'Error', Icon: OctagonX, className: 'text-red-700 dark:text-red-400' },
  { severity: 'warning', label: 'Warning', Icon: TriangleAlert, className: 'text-amber-700 dark:text-amber-400' },
]

/** The findings, errors first, each with the text it is about. */
function Findings({ findings }: { findings: readonly Finding[] }) {
  if (findings.length === 0) return <p className="text-muted-foreground">No findings.</p>
  return (
    <ol aria-label="Findings" className="flex flex-col gap-2">
      {severities.flatMap(({ severity, label, Icon, className }) =>
        findings
          .filter((finding) => finding.severity === severity)
          .map((finding, index) => (
            <li key={`${severity}-${index}`} className="flex flex-col gap-1 border-l-2 pl-2">
              <span className={cn('inline-flex items-center gap-1 text-xs font-semibold', className)}>
                <Icon aria-hidden="true" className="size-3.5" />
                {label}
              </span>
              {finding.excerpt && (
                <blockquote className="rounded bg-muted px-2 py-1 font-mono text-xs break-words">{finding.excerpt}</blockquote>
              )}
              <p>{finding.message}</p>
            </li>
          )),
      )}
    </ol>
  )
}

/**
 * What the judge said about a text or custom widget, in the card's header: "Reviewed ✓",
 * "2 findings" (warnings), "Failed: 2 findings", or "Not reviewed" (with why, in a
 * tooltip). It opens the findings, with "Review again" in the card's run.
 *
 * The verdict comes with the widget, which the live stream reads again when the worker
 * stores a new one; a review asked for here shows at once, until the widget is read again.
 */
export function VerdictBadge({ widget, runId }: { widget: Widget; runId: Id | null }) {
  const queryClient = useQueryClient()
  // The verdict "Review again" returned, for the widget as it was then.
  const [fresh, setFresh] = useState<{ base: Verdict | null | undefined; verdict: Verdict | null | undefined } | null>(null)
  const verdict = fresh && fresh.base === widget.verdict ? fresh.verdict : widget.verdict
  const review = useMutation({
    mutationFn: () => reviewWidget(widget.id, runId),
    onSuccess: async (reviewed) => {
      setFresh({ base: widget.verdict, verdict: reviewed.verdict })
      queryClient.setQueryData(keys.widget(widget.id), reviewed)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.projectWidgets(widget.project_id) }),
        queryClient.invalidateQueries({ queryKey: judgeKeys.verdicts(widget.project_id) }),
        widget.session_id && queryClient.invalidateQueries({ queryKey: keys.sessionWidgets(widget.session_id) }),
      ])
    },
  })

  const { label, Icon, className, reason } = verdictSummary(verdict)
  const trigger = (
    <PopoverTrigger asChild>
      <Button
        type="button"
        variant="outline"
        size="xs"
        className={cn('h-5 shrink-0 rounded-full px-2 text-xs font-medium', className)}
      >
        <Icon aria-hidden="true" data-icon="inline-start" />
        {label}
      </Button>
    </PopoverTrigger>
  )
  return (
    <Popover>
      {reason ? <Hint label={reason}>{trigger}</Hint> : trigger}
      <PopoverContent align="end" className="w-96 max-w-[calc(100vw-2rem)]" aria-label="The judge’s review">
        <div className="flex flex-col gap-1">
          <p className="font-semibold">The judge’s review</p>
          {verdict && verdict.outcome !== 'unchecked' ? (
            <p className="text-xs text-muted-foreground">
              {verdict.model ? `${verdict.model}, ` : ''}
              <Time value={verdict.checked_at} />
              {verdict.blocking && <span className="font-medium text-red-700 dark:text-red-400"> · stops report versions</span>}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">{reason}</p>
          )}
        </div>
        {verdict && verdict.outcome !== 'unchecked' && <Findings findings={verdict.findings} />}
        {review.error && <ErrorNotice error={review.error} prefix="Not reviewed:" />}
        <div>
          <Button type="button" variant="outline" size="sm" disabled={review.isPending} onClick={() => review.mutate()}>
            <RefreshCw aria-hidden="true" data-icon="inline-start" className={cn(review.isPending && 'animate-spin')} />
            {review.isPending ? 'Reviewing…' : 'Review again'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
