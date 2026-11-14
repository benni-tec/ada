import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Provenance } from './provenance'

test('an external agent shows its client name, or no creator when it gave none', () => {
  const { rerender } = render(<Provenance actor={{ kind: 'external_agent', name: 'claude-code' }} at="2026-11-14T08:00:00Z" note="Why" />)
  expect(screen.getByText('claude-code')).toBeInTheDocument()

  rerender(<Provenance actor={{ kind: 'external_agent', name: '' }} at="2026-11-14T08:00:00Z" note="Why" />)
  expect(screen.queryByText(/External agent/)).not.toBeInTheDocument()
  expect(screen.getByText('Why')).toBeInTheDocument()
})
