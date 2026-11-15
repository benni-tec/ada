import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { LiveTime } from '@/components/live-time'
import { ErrorNotice } from '@/components/notices'
import { deliveriesQuery, type Id } from '@/lib/api'
import { browserReceipts } from '@/lib/browser-alerts'

export function Deliveries({ projectId, alertId, ruleId, browserAlertId }: {
  projectId: Id
  alertId?: Id
  ruleId?: Id
  browserAlertId?: Id
}) {
  const query = useQuery(deliveriesQuery(projectId))
  const [, update] = useState(0)
  useEffect(() => {
    const receive = () => update((value) => value + 1)
    window.addEventListener('ada.browser-receipt', receive)
    return () => window.removeEventListener('ada.browser-receipt', receive)
  }, [])
  const receipt = browserReceipts.get(alertId ?? browserAlertId ?? '')
  const deliveries = query.data?.filter((delivery) =>
    alertId ? delivery.alert_id === alertId : delivery.test && delivery.rule_id === ruleId,
  )
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      {query.error && <ErrorNotice error={query.error} prefix="Deliveries cannot be loaded:" />}
      {deliveries?.map((delivery) => (
        <div key={delivery.id}>
          {delivery.test && <strong>Test · </strong>}
          {delivery.channel === 'email' ? 'Email' : delivery.channel === 'ntfy' ? 'ntfy' : 'Webhook'}
          {' → '}{delivery.target} · {delivery.status}
          {delivery.http_status && ` · ${delivery.http_status}`} · <LiveTime value={delivery.created_at} />
          {delivery.detail && (delivery.channel === 'email' ? (
            <details>
              <summary>Simulated email</summary>
              <pre className="whitespace-pre-wrap">{delivery.detail}</pre>
            </details>
          ) : <span> · {delivery.detail}</span>)}
        </div>
      ))}
      {receipt && <p>{browserAlertId && 'Test · '}Browser notification shown · <LiveTime value={receipt.at} /></p>}
    </div>
  )
}
