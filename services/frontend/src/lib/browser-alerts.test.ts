// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'

import { browserReceipts, enableBrowserAlerts, showBrowserAlert } from './browser-alerts'

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); browserReceipts.clear() })

it('requests permission on enable, displays a tagged notification and records its time; denial uses a toast', async () => {
  const requestPermission = vi.fn().mockResolvedValue('granted')
  const notification = { onclick: null, close: vi.fn() }
  const Notification = vi.fn(function () { return notification })
  Object.assign(Notification, { permission: 'granted', requestPermission })
  vi.stubGlobal('Notification', Notification)
  expect(requestPermission).not.toHaveBeenCalled()
  expect(await enableBrowserAlerts()).toBe('granted')
  expect(requestPermission).toHaveBeenCalledOnce()
  expect(showBrowserAlert('Low stock', 'item: insulin', 'alert-1', 'project-1')).toBe(true)
  expect(Notification).toHaveBeenCalledWith('Low stock', { body: 'item: insulin', tag: 'alert-1' })
  expect(notification.onclick).toBeTypeOf('function')
  expect(browserReceipts.get('alert-1')?.at).toMatch(/^\d{4}-/)
  const toast = vi.fn()
  window.addEventListener('ada.alert-toast', toast, { once: true })
  Object.assign(Notification, { permission: 'denied' })
  expect(showBrowserAlert('Low stock', 'item: insulin', 'alert-2', 'project-1')).toBe(false)
  expect(toast).toHaveBeenCalledOnce()
  expect(browserReceipts.has('alert-2')).toBe(false)
})
