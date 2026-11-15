import { afterEach, expect, test, vi } from 'vitest'

import { snapshotAnswer, snapshotWidget } from './widgets'

afterEach(() => vi.restoreAllMocks())

test('a widget is drawn unseen, light and as tall as its content, and answers with its picture', async () => {
  vi.spyOn(crypto, 'randomUUID').mockReturnValue('0-0-0-0-1')
  const picture = snapshotWidget({ id: 'w1', type: 'map' }, 'r2')
  const frame = document.querySelector('iframe')!
  expect(frame.src).toBe('http://localhost:5174/map.html#widget=w1&run=r2&theme=light&fit=content')
  expect(frame).toHaveAttribute('aria-hidden', 'true')
  expect(frame.style.opacity).toBe('0')
  const asked = vi.spyOn(frame.contentWindow!, 'postMessage')
  frame.dispatchEvent(new Event('load'))
  expect(asked).toHaveBeenCalledWith({ type: 'ada:snapshot', id: '0-0-0-0-1' }, '*')

  // Another frame's answer, or one to another request, is not this one's.
  window.dispatchEvent(new MessageEvent('message', { source: window, data: { type: 'ada:snapshot', id: '0-0-0-0-1', error: 'no' } }))
  const answer = { type: 'ada:snapshot', id: '0-0-0-0-1', image: 'data:image/png;base64,AAA', width: 720, height: 300 }
  window.dispatchEvent(new MessageEvent('message', { source: frame.contentWindow, data: answer }))
  await expect(picture).resolves.toEqual({ image: 'data:image/png;base64,AAA', width: 720, height: 300 })
  expect(document.querySelector('iframe')).toBeNull()
})

test('a widget that cannot draw itself says why', () => {
  expect(snapshotAnswer({ type: 'ada:snapshot', id: 's1', error: 'no canvas' }, 's1')).toEqual({ error: 'no canvas' })
  expect(snapshotAnswer({ type: 'ada:snapshot', id: 's2', error: 'no canvas' }, 's1')).toBeNull()
  expect(snapshotAnswer({ type: 'ada:resize', height: 10 }, 's1')).toBeNull()
})
