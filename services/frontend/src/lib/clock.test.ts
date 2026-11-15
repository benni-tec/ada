import { expect, test } from 'vitest'

import { ago } from './clock'

test('how long ago, in its largest whole unit', () => {
  const now = Date.parse('2026-11-15T12:00:00Z')
  expect(ago(now - 40_000, now)).toBe('40 s ago')
  expect(ago(now - 3 * 60_000 - 5_000, now)).toBe('3 min ago')
  expect(ago(now - 2 * 3_600_000, now)).toBe('2 h ago')
  expect(ago(now - 5 * 86_400_000, now)).toBe('5 d ago')
  expect(ago(now + 3_000, now)).toBe('0 s ago')
})
