import type { AccessKind, DataFormat, FreshnessKind, FreshnessPolicy } from './api'

export const accessLabels: Record<AccessKind, string> = {
  url: 'URL',
  request: 'Request',
  browser: 'Browser',
  document: 'Document',
}

export const formatLabels: Record<DataFormat, string> = {
  csv: 'CSV',
  json: 'JSON',
  parquet: 'Parquet',
  pdf: 'PDF',
}

export const freshnessLabels: Record<FreshnessKind, string> = {
  manual: 'Only when asked',
  ttl: 'After a time',
  probe: 'When the source says it changed',
  push: 'When the source pushes',
}

/** How a source stays fresh, in words, e.g. "every 24 h". */
export function describeFreshness(freshness: FreshnessPolicy): string {
  switch (freshness.kind) {
    case 'manual':
      return 'only when asked'
    case 'ttl':
      return freshness.ttl_seconds ? `every ${describeSeconds(freshness.ttl_seconds)}` : 'after a time'
    case 'probe':
      return 'when it changed'
    case 'push':
      return 'when pushed'
  }
}

function describeSeconds(seconds: number): string {
  if (seconds % 86_400 === 0) return `${seconds / 86_400} d`
  if (seconds % 3_600 === 0) return `${seconds / 3_600} h`
  if (seconds % 60 === 0) return `${seconds / 60} min`
  return `${seconds} s`
}
