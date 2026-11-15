import { listAlerts, type LiveEvent } from '@/lib/api'

export type BrowserReceipt = { alertId: string; at: string }
export const browserReceipts = new Map<string, BrowserReceipt>()
const enabledKey = 'ada.browser-alerts'

export async function enableBrowserAlerts(): Promise<NotificationPermission | 'unsupported'> {
  localStorage.setItem(enabledKey, 'true')
  if (!('Notification' in window)) return 'unsupported'
  return Notification.requestPermission()
}

export function showBrowserAlert(title: string, body: string, alertId: string, projectId: string): boolean {
  const url = `/projects/${encodeURIComponent(projectId)}/alerts`
  if ('Notification' in window && Notification.permission === 'granted') {
    try {
      const notification = new Notification(title, { body, tag: alertId })
      notification.onclick = () => { window.focus(); window.location.assign(url); notification.close() }
      browserReceipts.set(alertId, { alertId, at: new Date().toISOString() })
      window.dispatchEvent(new Event('ada.browser-receipt'))
      return true
    } catch { /* Some browsers expose the API but cannot display notifications. */ }
  }
  window.dispatchEvent(new CustomEvent('ada.alert-toast', { detail: { title, body, url } }))
  return false
}

export async function notifyBrowser(event: LiveEvent): Promise<void> {
  if (event.type !== 'alert.firing' || localStorage.getItem(enabledKey) !== 'true') return
  const views = await listAlerts(event.project_id, null)
  const view = views.find(({ alert }) => alert.id === event.payload.alert_id)
  if (!view) return
  const body = Object.entries(view.alert.key).map(([name, value]) => `${name}: ${value}`).join(', ') || 'all rows'
  showBrowserAlert(view.rule.name, body, view.alert.id, event.project_id)
}
