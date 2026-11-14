import type { ReactNode } from 'react'

import { statusWords, type Deadline, type Evaluation } from '@/lib/api'

// The patient pathway model's result on a case, condensed for the side sheet: the trigger
// and the next deadline, the deadlines, where the days go, survival second (weaker
// evidence), and the support to offer.

const deadlineClasses: Record<Deadline['status'], string> = {
  overdue: 'bg-orange-700 text-white dark:bg-orange-500 dark:text-black',
  due: 'border',
  late: 'border',
  met: 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300',
  not_applicable: 'border text-muted-foreground',
}

function Label({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">{children}</h3>
}

export function PathwayResult({ evaluation, summary }: { evaluation: Evaluation; summary: string }) {
  const { trigger, deadlines, pathway, survival, flags } = evaluation
  const max = Math.max(60, ...pathway.map((row) => Math.max(row.days ?? 0, row.target ?? 0)))
  const pct = (days: number) => `${Math.min(100, (days / max) * 100)}%`
  return (
    <div className="flex flex-col gap-5" data-section="pathway-result">
      <p className="rounded-lg bg-foreground px-3.5 py-3 text-sm text-background">
        <strong>{summary}.</strong> {trigger.note}
      </p>

      {deadlines.length > 0 && (
        <section data-section="deadlines">
          <Label>Deadlines</Label>
          <ul>
            {deadlines.map((d) => (
              <li key={d.label} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-b py-2 text-sm last:border-b-0">
                <span>
                  {d.label}
                  <span className="block text-xs text-muted-foreground">
                    {d.rule}
                    {d.countries.length > 0 && ` · ${d.countries.join(', ')}`}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">{d.due_day != null ? `day ${d.due_day}` : ''}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${deadlineClasses[d.status]}`} data-status={d.status}>
                  {statusWords[d.status](d.by)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section data-section="days">
        <Label>Where the days go · {evaluation.days_behind} days behind target</Label>
        <div className="flex flex-col gap-1.5">
          {pathway.map((row) => (
            <div key={row.step} className="grid grid-cols-[minmax(110px,190px)_minmax(0,1fr)_84px] items-center gap-2.5 text-xs">
              <span>{row.label}</span>
              <div className="relative h-3 rounded-sm bg-muted">
                {row.days != null && (
                  <i
                    className={`absolute inset-y-0 left-0 rounded-l-sm bg-foreground ${row.patient_interval ? 'opacity-25' : 'opacity-70'}`}
                    style={{ width: pct(Math.min(row.days, row.target ?? row.days)) }}
                  />
                )}
                {row.gap > 0 && row.target != null && (
                  <b className="absolute inset-y-0 rounded-r-sm bg-orange-700 dark:bg-orange-500" style={{ left: pct(row.target), width: pct(row.gap) }} />
                )}
                {row.target != null && <s className="absolute -inset-y-[3px] w-0.5 bg-blue-600" style={{ left: pct(row.target) }} />}
              </div>
              <span className="text-right tabular-nums">
                {row.days == null ? (
                  <span className="text-muted-foreground">–</span>
                ) : row.gap > 0 ? (
                  <span className="font-semibold text-orange-700 dark:text-orange-400">
                    {row.days} d +{row.gap}
                  </span>
                ) : (
                  `${row.days} d${row.current ? ' so far' : ''}`
                )}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">Blue line: the target, from the Nordic standards.</p>
      </section>

      <section data-section="survival">
        <Label>Alive at 5 years, of 100 with this profile</Label>
        <div className="flex flex-wrap items-center gap-5">
          <span className="text-3xl font-bold tabular-nums">{survival.now}</span>
          <div role="img" aria-label={`${survival.now} of 100 alive at 5 years`} className="grid grid-cols-[repeat(20,8px)] gap-[3px]">
            {Array.from({ length: 100 }, (_, i) => (
              <span key={i} className={`size-2 rounded-full ${i < survival.now ? 'bg-foreground opacity-75' : 'bg-border'}`} />
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {survival.range_now.low}–{survival.range_now.high} across the settings ·{' '}
            {survival.on_target === survival.now ? 'the same' : survival.on_target} if the rest is on target
          </span>
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">Weaker evidence than the deadlines.</p>
      </section>

      <section data-section="support">
        <Label>Support to offer</Label>
        {flags.length > 0 ? (
          <ul className="list-disc pl-5 text-sm">
            {flags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing flagged for this case.</p>
        )}
      </section>
    </div>
  )
}
