import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { SectionView } from '@/components/cases/result-sheet'
import type { ModelVersion, Section, StatisticalModel } from '@/lib/api'

import { project, renderAt, serveApi, web } from './app'

// The trial matcher: a model of its own kind on the cancer case type. Its card shows what it
// pinned and how it matches; its result lists trials, Finnish sites first, eligibility folded.

const matcher: StatisticalModel = {
  id: 'm2',
  project_id: 'p1',
  name: 'Trial matcher',
  description: 'Recruiting Nordic cancer trials.',
  kind: 'trial_matcher',
  latest_version: 1,
  case_type_id: 'ct1',
  auto_run: false,
  created_by: web,
  created_at: '2026-11-15T10:00:00Z',
}

const version: ModelVersion = {
  id: 'v2',
  model_id: 'm2',
  version: 1,
  spec: {
    kind: 'trial_matcher',
    operator_id: 'op_case_trials',
    groups: { lung: 'lung', colorectal: 'colorectal', pancreas: 'pancreas' },
    intended_use: 'Educational: recruiting trials to discuss.',
    cautions: ['Matched on cancer group, sex and age only.'],
  },
  compiled: {
    kind: 'trial_matcher',
    read_at: '2026-11-15T09:00:00Z',
    run_id: 'run-1',
    warnings: [],
    trials: [
      {
        nct_id: 'NCT1',
        title: 'Lung trial in Helsinki',
        phase: 'PHASE2',
        conditions: 'Non-small cell lung cancer',
        eligibility: 'Inclusion: adults.',
        cancer_groups: ['lung'],
        sex: 'ALL',
        min_age_years: 18,
        max_age_years: 75,
        recruiting_countries: ['Finland'],
        finnish_site: true,
        nearest: { helsinki: { facility: 'HUS', city: 'Helsinki', country: 'Finland', km: 4.6 } },
        url: 'https://clinicaltrials.gov/study/NCT1',
      },
    ],
  },
  created_by: web,
  created_at: '2026-11-15T10:00:00Z',
}

test("a trial matcher's page shows its card, its cases, and no survival tabs", async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/models': [matcher],
    'GET /api/projects/p1/case-types': [],
    'GET /api/models/m2': matcher,
    'GET /api/models/m2/versions/latest': version,
    'GET /api/case-types/ct1': { id: 'ct1', project_id: 'p1', name: 'Suspected cancer pathway', description: '', fields: [], revision: 1, created_by: web, created_at: '2026-11-15T10:00:00Z' },
    'GET /api/models/m2/cases': [],
  })
  renderAt('/projects/p1/models/m2')
  expect(await screen.findByRole('heading', { name: 'Pinned trials' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Lung trial in Helsinki' })).toHaveAttribute('href', 'https://clinicaltrials.gov/study/NCT1')
  expect(screen.getByText('op_case_trials')).toBeInTheDocument()
  const tabs = screen.getByRole('tablist')
  expect(within(tabs).getByRole('tab', { name: 'Cases' })).toBeInTheDocument()
  expect(within(tabs).queryByRole('tab', { name: 'Evaluation' })).not.toBeInTheDocument()
  expect(within(tabs).queryByRole('tab', { name: 'Population' })).not.toBeInTheDocument()
})

test('a trial result lists the trials with their nearest site, age fit and folded eligibility', () => {
  const section: Section = {
    kind: 'trial_matcher',
    title: 'Trial matcher',
    summary: '2 recruiting trials, 1 with a Finnish site',
    status: 'info',
    columns: { trials: 2 },
    attention: { open: false },
    body: {
      city: 'oulu',
      total: 2,
      matches: [
        { nct_id: 'NCT1', title: 'Lung trial in Helsinki', finnish_site: true, countries: ['Finland'], nearest: { facility: 'OYS', city: 'Oulu', country: 'Finland', km: 3 }, age: 'fits', eligibility: 'Inclusion: adults.', url: 'https://clinicaltrials.gov/study/NCT1' },
        { nct_id: 'NCT2', title: 'Women-only trial', finnish_site: false, countries: ['Sweden'], nearest: { city: 'Umeå', country: 'Sweden', km: 410 }, age: 'partly', url: 'https://clinicaltrials.gov/study/NCT2' },
      ],
    },
  }
  render(<SectionView section={section} />)
  expect(screen.getByText('2 recruiting trials, 1 with a Finnish site')).toBeInTheDocument()
  expect(screen.getByText(/Distances from Oulu/)).toBeInTheDocument()
  const items = screen.getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('Finnish site')
  expect(items[0]).toHaveTextContent('OYS, Oulu, Finland, 3 km')
  expect(items[1]).toHaveTextContent('age group only partly inside the limits')
  expect(screen.getByText('Eligibility, as registered')).toBeInTheDocument()
})
