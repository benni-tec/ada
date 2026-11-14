import { expect, test } from 'vitest'

import type { AlertView } from '@/lib/api'

import { worstActive } from './labels'

const view = (severity: AlertView['rule']['severity'], state: AlertView['alert']['state'] = 'firing') =>
  ({ alert: { state }, rule: { severity } }) as AlertView

test('the colour of a count is that of its most severe active alert: red only for critical', () => {
  expect(worstActive([view('warning'), view('info')])).toBe('warning')
  expect(worstActive([view('warning'), view('critical'), view('info')])).toBe('critical')
  expect(worstActive([view('critical', 'resolved'), view('info')])).toBe('info')
  expect(worstActive([view('warning', 'resolved')])).toBeNull()
})
