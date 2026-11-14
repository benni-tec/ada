import { Badge } from '@/components/ui/badge'
import type { Section } from '@/lib/api'

const statusClasses: Record<Section['status'], string> = {
  urgent: 'border-transparent bg-orange-700 text-white dark:bg-orange-500 dark:text-black',
  warn: 'border-transparent bg-orange-50 text-orange-800 dark:bg-orange-950 dark:text-orange-300',
  ok: 'border-transparent bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300',
  info: 'border-border text-muted-foreground',
}

/** A result's summary, coloured by how pressing it is. */
export function ResultBadge({ section, className }: { section: Section; className?: string }) {
  return (
    <Badge variant="outline" data-status={section.status} className={`${statusClasses[section.status]} ${className ?? ''}`}>
      {section.summary}
    </Badge>
  )
}

/** Whether a model runs on every save of a case, or only when someone asks. */
export function RunsBadge({ autoRun, long }: { autoRun: boolean; long?: boolean }) {
  return autoRun ? (
    <Badge variant="outline" className="border-transparent bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
      {long ? 'Runs automatically' : 'Automatically'}
    </Badge>
  ) : (
    <Badge variant="outline" className="text-muted-foreground">
      {long ? 'Runs on request' : 'On request'}
    </Badge>
  )
}
