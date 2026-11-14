import type { Loaded } from '@/lib/runtime'
import type { Roles, Widget, WidgetData } from '@/lib/types'

export function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: 'w1',
    project_id: 'p1',
    session_id: 's1',
    operator_id: 'op_1',
    type: 'value',
    title: 'Screening coverage',
    spec: {},
    note: '',
    ...overrides,
  }
}

/** Yearly screening coverage for two regions, with a confidence interval and one
 * suppressed value. */
export function coverage(overrides: Partial<WidgetData> = {}): WidgetData {
  return {
    widget_id: 'w1',
    run_id: 'r1',
    output: { columns: [], roles: coverageRoles },
    columns: [
      { name: 'period_start', type: 'date' },
      { name: 'period_end', type: 'date' },
      { name: 'region', type: 'text' },
      { name: 'coverage', type: 'number' },
      { name: 'coverage_low', type: 'number' },
      { name: 'coverage_high', type: 'number' },
      { name: 'suppressed', type: 'boolean' },
    ],
    rows: [
      ['2022-01-01', '2022-12-31', 'North', 61.5, 59.1, 63.9, false],
      ['2023-01-01', '2023-12-31', 'North', null, null, null, true],
      ['2024-01-01', '2024-12-31', 'North', 64.25, 62, 66.5, false],
      ['2022-01-01', '2022-12-31', 'South', 70, 68, 72, false],
      ['2023-01-01', '2023-12-31', 'South', 71, 69, 73, false],
      ['2024-01-01', '2024-12-31', 'South', 72.5, 70, 75, false],
    ],
    truncated: false,
    is_scenario: false,
    is_stale: false,
    ...overrides,
  }
}

export const coverageRoles: Roles = {
  time: { start: 'period_start', end: 'period_end' },
  measures: [{ value: 'coverage', lower: 'coverage_low', upper: 'coverage_high', suppressed: 'suppressed' }],
}

export function loaded(overrides: Partial<Loaded> = {}): Loaded {
  return { widget: widget(), data: coverage(), roles: coverageRoles, fetchedAt: new Date('2026-11-14T12:00:00Z'), ...overrides }
}
