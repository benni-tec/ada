import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { AdaMark, Vahti, type VahtiPose } from './vahti'

const poses: VahtiPose[] = ['watching', 'searching', 'asleep', 'puzzled', 'peek']

test('every pose is a labelled image, and an empty label hides it from screen readers', () => {
  const { container } = render(
    <>
      {poses.map((pose) => (
        <Vahti key={pose} pose={pose} />
      ))}
      <Vahti pose="watching" label="" />
    </>,
  )
  expect(screen.getAllByRole('img', { name: /^Vahti/ })).toHaveLength(poses.length)
  expect(container.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(1)
  const ids = [...container.querySelectorAll('filter')].map((f) => f.id)
  expect(new Set(ids).size).toBe(ids.length)
})

test('the wordmark reads as ADA', () => {
  render(<AdaMark />)
  expect(screen.getByRole('img', { name: 'ADA' })).toBeInTheDocument()
})

test('the eyes stop following the pointer once reduced motion is switched on', () => {
  const listeners = new Set<() => void>()
  const query = { matches: false, addEventListener: (_: string, f: () => void) => listeners.add(f), removeEventListener: (_: string, f: () => void) => listeners.delete(f) }
  vi.stubGlobal('matchMedia', () => query)
  vi.stubGlobal('requestAnimationFrame', (f: FrameRequestCallback) => (f(0), 1))
  const { container } = render(<Vahti pose="peek" follow />)
  const pupil = () => container.querySelector<SVGGElement>('.v-pupils')?.style.transform
  const resting = pupil()
  fireEvent.pointerMove(window, { clientX: 400, clientY: 0 })
  expect(pupil()).not.toBe(resting)
  act(() => {
    query.matches = true
    listeners.forEach((f) => f())
  })
  expect(pupil()).toBe(resting)
  fireEvent.pointerMove(window, { clientX: 0, clientY: 400 })
  expect(pupil()).toBe(resting)
  vi.unstubAllGlobals()
})
