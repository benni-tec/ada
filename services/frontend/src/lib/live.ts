import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState } from 'react'

import type { Id, LiveEvent } from '@/lib/api'
import { forgetLiveParts, receivePart } from '@/lib/agent-turns'
import { effectsOf, EVENT_TYPES } from '@/lib/events'

export type Connection = 'connecting' | 'open' | 'reconnecting'

export type Live = {
  connection: Connection
  /** Increases whenever widget frames should reload; frames use it as their key. */
  widgetEpoch: number
}

export const LiveContext = createContext<Live>({ connection: 'connecting', widgetEpoch: 0 })

/** Waits 1 s, 2 s, 4 s … up to 30 s between attempts, so a backend that is down is not
 * hammered by every open tab. */
export function retryDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 30_000)
}

/**
 * Follows a project's live stream: one EventSource per open project. Each event
 * invalidates the queries it affects. The connection is closed on error and reopened with
 * backoff instead of relying on the browser's retry, which gives up for good on an HTTP
 * error; after a reconnect everything is refetched, since events may have been missed.
 */
export function useProjectEvents(projectId: Id): Live {
  const queryClient = useQueryClient()
  const [connection, setConnection] = useState<Connection>('connecting')
  const [widgetEpoch, setWidgetEpoch] = useState(0)

  useEffect(() => {
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let reconnecting = false

    const onEvent = (message: MessageEvent<string>) => {
      let event: LiveEvent
      try {
        event = JSON.parse(message.data) as LiveEvent
      } catch {
        return
      }
      const { invalidate, reloadWidgets, turnPart, turnFinished } = effectsOf(event)
      if (turnPart) receivePart(queryClient, turnPart.turnId, turnPart.index, turnPart.part)
      if (turnFinished) forgetLiveParts(turnFinished)
      for (const queryKey of invalidate) void queryClient.invalidateQueries({ queryKey })
      if (reloadWidgets) setWidgetEpoch((epoch) => epoch + 1)
    }

    const connect = () => {
      source = new EventSource(`/api/projects/${encodeURIComponent(projectId)}/events`)
      for (const type of EVENT_TYPES) source.addEventListener(type, onEvent)
      source.onopen = () => {
        attempt = 0
        setConnection('open')
        if (reconnecting) {
          // Parts were missed too: every turn is fetched again and continues from there.
          forgetLiveParts()
          void queryClient.invalidateQueries()
          setWidgetEpoch((epoch) => epoch + 1)
        }
      }
      source.onerror = () => {
        source?.close()
        reconnecting = true
        setConnection('reconnecting')
        timer = setTimeout(connect, retryDelay(attempt++))
      }
    }

    connect()
    return () => {
      clearTimeout(timer)
      source?.close()
    }
  }, [projectId, queryClient])

  return { connection, widgetEpoch }
}

export function useLive(): Live {
  return useContext(LiveContext)
}
