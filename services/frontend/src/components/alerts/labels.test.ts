import { expect, test } from 'vitest'

import type { AlertView } from '@/lib/api'

import { mostSevereFirst, worstActive } from './labels'

const view = (severity: AlertView['rule']['severity'], state: AlertView['alert']['state'] = 'firing') =>
  ({ alert: { state }, rule: { severity } }) as AlertView

test('the colour of a count is that of its most severe active alert: red only for critical', () => {
  expect(worstActive([view('warning'), view('info')])).toBe('warning')
  expect(worstActive([view('warning'), view('critical'), view('info')])).toBe('critical')
  expect(worstActive([view('critical', 'resolved'), view('info')])).toBe('info')
  expect(worstActive([view('warning', 'resolved')])).toBeNull()
})

test('alerts are listed most severe first, equal severities in their order', () => {
  const views = [view('warning'), view('info'), view('critical'), view('warning')]
  expect(mostSevereFirst(views).map((v) => v.rule.severity)).toEqual(['critical', 'warning', 'warning', 'info'])
  expect(mostSevereFirst(views)[1]).toBe(views[0])
})
