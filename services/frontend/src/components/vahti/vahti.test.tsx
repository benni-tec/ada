import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

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
