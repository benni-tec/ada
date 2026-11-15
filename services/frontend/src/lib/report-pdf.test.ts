import { expect, test } from 'vitest'

import { citation, reportUrl } from './report-pdf'

test('a widget cites its sources by number, runs joined', () => {
  expect(citation([1, 2, 3, 7, 9, 10])).toBe('[1–3], [7], [9–10]')
  expect(citation([4])).toBe('[4]')
  expect(citation([])).toBe('')
})

test('the PDF links back to the version it was made of, on the host it was made on', () => {
  expect(reportUrl('https://ada.test', { id: 'rep1', project_id: 'p1' }, { version: '1.1.0' })).toBe(
    'https://ada.test/projects/p1/reports/rep1?version=1.1.0',
  )
})
