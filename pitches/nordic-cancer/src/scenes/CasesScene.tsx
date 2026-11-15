import { AbsoluteFill, Sequence, spring, useCurrentFrame, useVideoConfig } from 'remotion'

import { CaseData } from '@/components/cases/case-data'
import { ResultBadge, RunsBadge } from '@/components/cases/labels'
import { SectionView } from '@/components/cases/result-sheet'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ownFields, type CaseState, type CaseType, type ModelOnCase } from '@/lib/api'

import caseTypeJson from '../data/case-type.json'
import stateJson from '../data/case.json'
import modelsJson from '../data/case-models.json'
import { Cursor, type Point } from '../Cursor'
import { s } from '../frame'
import { LowerThird } from '../LowerThird'

// A synthetic case from the dev database (SYN-00291) with the pathway model's real result.
const caseType = caseTypeJson as unknown as CaseType
const full = stateJson as unknown as CaseState
const models = modelsJson as unknown as ModelOnCase[]
const pathway = models[0]

/** The steps the case has, in pathway order, revealed one at a time. */
const DAYS = Object.entries((full.case.values.days ?? {}) as Record<string, number>)

/** The case as the clinician has entered it by `frame`: one more step every 0.4 seconds. */
function caseAt(frame: number): CaseState {
  const shown = Math.min(DAYS.length, Math.floor(frame / s(0.4)) + 1)
  return { ...full, case: { ...full.case, values: { ...full.case.values, days: Object.fromEntries(DAYS.slice(0, shown)) } } }
}

const SAVED = s(0.4) * DAYS.length + s(0.3)
const SHEET = s(5)

/** The pointer: along the steps as they are entered, to the result, a click on View result,
 * then the overdue deadline, the late step and the survival in the sheet. */
const POINTER: Point[] = [
  { at: 0, x: 1500, y: 980 },
  { at: 10, x: 1110, y: 330 },
  { at: 22, x: 1110, y: 372 },
  { at: 34, x: 1110, y: 414 },
  { at: SAVED + 16, x: 1120, y: 892 },
  { at: SHEET - 10, x: 1560, y: 892 },
  { at: SHEET - 5, x: 1560, y: 892, click: true },
  { at: s(6.5), x: 1800, y: 300 },
  { at: s(11.5), x: 1222, y: 682 },
  { at: s(17.5), x: 1150, y: 952 },
]

export const CASES_FRAMES = s(26)

const FOCUS_CSS = `
[data-focus] [data-section]:not([data-section="pathway-result"]) { opacity: 0.22; }
[data-focus="deadlines"] [data-section="deadlines"],
[data-focus="days"] [data-section="days"],
[data-focus="survival"] [data-section="survival"],
[data-focus="survival"] [data-section="support"] { opacity: 1 !important; }
`

/** The central tool: a case, the models that run on it, and what they give back. */
export function CasesScene() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const state = caseAt(frame)
  const ran = frame >= SAVED
  const sheet = spring({ frame: frame - SHEET, fps, config: { damping: 200 }, durationInFrames: 14 })
  // The part of the result the banner talks about; the rest dims.
  const focus = frame < s(6) ? null : frame < s(11) ? 'deadlines' : frame < s(17) ? 'days' : 'survival'
  return (
    <AbsoluteFill className="bg-background text-foreground">
      <style>{FOCUS_CSS}</style>
      <TooltipProvider>
        <div style={{ zoom: 1.45, padding: '28px 40px' }} className="flex max-w-[1180px] flex-col gap-4">
          <div>
            <div className="text-sm text-muted-foreground">Cases / {caseType.name}</div>
            <div className="flex items-center justify-between">
              <h1 className="font-mono text-2xl font-semibold">{full.case.key}</h1>
              {ran && pathway.latest && <ResultBadge section={pathway.latest.section} className="h-6 px-2.5 text-sm" />}
            </div>
            <div className="text-sm text-muted-foreground">Synthetic</div>
          </div>
          <CaseData
            caseType={caseType}
            state={state}
            own={ownFields(caseType, models)}
            clockStart={ran ? ((pathway.latest?.section.columns.clock_start as number | undefined) ?? null) : null}
            onSave={async () => undefined}
            saving={false}
            error={null}
          />
          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-3 font-semibold">Models</header>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="px-4 text-xs text-muted-foreground">Model</TableHead>
                  <TableHead className="px-4 text-xs text-muted-foreground">Runs</TableHead>
                  <TableHead className="px-4 text-xs text-muted-foreground">Latest result</TableHead>
                  <TableHead className="px-4" />
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow>
                  <TableCell className="px-4 py-3 font-medium">{pathway.name}</TableCell>
                  <TableCell className="px-4 py-3">
                    <RunsBadge autoRun={pathway.auto_run} />
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    {ran && pathway.latest ? (
                      <ResultBadge section={pathway.latest.section} />
                    ) : (
                      <span className="text-xs text-muted-foreground">Running…</span>
                    )}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-right">
                    <Button variant="outline" disabled={!ran}>
                      View result
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </section>
        </div>
        {frame >= SHEET && pathway.latest && (
          <div
            className="absolute inset-y-0 right-0 overflow-hidden border-l bg-background"
            style={{ width: 1040, transform: `translateX(${(1 - sheet) * 1040}px)`, boxShadow: '-24px 0 60px rgba(0,0,0,0.15)' }}
          >
            <div style={{ zoom: 1.35, padding: '24px 28px' }}>
              <div className="text-sm text-muted-foreground">{full.case.key} · {caseType.name}</div>
              <div className="mb-4 text-lg font-semibold">{pathway.name}</div>
              <div data-focus={focus ?? undefined}>
                <SectionView section={pathway.latest.section} />
              </div>
            </div>
          </div>
        )}
      </TooltipProvider>
      <Cursor path={POINTER} />
      <Sequence durationInFrames={s(3)}>
        <LowerThird title="A case: one patient's pathway" line="Entered step by step by the clinician (synthetic data)" exitAt={s(2.6)} />
      </Sequence>
      <Sequence from={s(3)} durationInFrames={s(2.4)}>
        <LowerThird title="Models run on every save" line="The patient pathway model, from the Nordic standards" exitAt={s(2)} />
      </Sequence>
      <Sequence from={s(5.6)} durationInFrames={s(5.2)}>
        <LowerThird title="The clock Finland is missing" line="Imaging after suspicion: overdue by 2 days" accent="#f97316" exitAt={s(4.8)} />
      </Sequence>
      <Sequence from={s(11)} durationInFrames={s(5.8)}>
        <LowerThird title="Where the days go" line="Each step against the Danish, Norwegian and Swedish targets" exitAt={s(5.4)} />
      </Sequence>
      <Sequence from={s(17)}>
        <LowerThird title="Evidence a clinician can act on" line="Survival and delay effects, each with its published source" accent="#22c55e" />
      </Sequence>
    </AbsoluteFill>
  )
}
