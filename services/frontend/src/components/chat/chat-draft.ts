import { createContext, useCallback, useContext, useMemo, useState } from 'react'

import type { Context, Id, Pipeline, Widget } from '@/lib/api'

/**
 * A chip on the message being written: what the message is about. One chip may carry
 * several contexts, e.g. "Add widget" on a dashboard: the pipeline, and the dashboard and
 * slot to put the widget in, removed together.
 */
export type Chip = {
  /** Same key, same chip: adding it twice keeps one. */
  key: string
  label: string
  context: Context[]
}

export type ChatDraft = {
  chips: Chip[]
  addChip: (chip: Chip) => void
  removeChip: (key: string) => void
  clearChips: () => void
  /** Increases when something asks the composer to take the focus (e.g. a chip added from
   * elsewhere on the page, so the person can say what they want right away). */
  focusRequest: number
}

/**
 * The draft is held by the page, not the composer: "Add widget" sits elsewhere on the page
 * (a dashboard's header, an empty slot) and puts its chip on the message from there.
 */
export function useChatDraftState(): ChatDraft {
  const [chips, setChips] = useState<Chip[]>([])
  const [focusRequest, setFocusRequest] = useState(0)
  const addChip = useCallback((chip: Chip) => {
    setChips((current) => [...current.filter((existing) => existing.key !== chip.key), chip])
    setFocusRequest((value) => value + 1)
  }, [])
  const removeChip = useCallback((key: string) => setChips((current) => current.filter((chip) => chip.key !== key)), [])
  const clearChips = useCallback(() => setChips([]), [])
  return useMemo(
    () => ({ chips, addChip, removeChip, clearChips, focusRequest }),
    [chips, addChip, removeChip, clearChips, focusRequest],
  )
}

export const ChatDraftContext = createContext<ChatDraft | null>(null)

/** The page's draft; a composer outside one keeps its own (useChatDraftState). */
export function useChatDraft(): ChatDraft | null {
  return useContext(ChatDraftContext)
}

/** The chip "Add widget" puts on the message: the pipeline, and on a dashboard also the
 * dashboard and the slot the widget is for (none: a new slot). */
export function pipelineChip(pipeline: Pick<Pipeline, 'operator_id' | 'name'>, dashboard?: { id: Id; name: string; slot?: string }): Chip {
  const context: Context[] = [{ kind: 'pipeline', operator_id: pipeline.operator_id }]
  if (!dashboard) return { key: 'pipeline:' + pipeline.operator_id, label: 'Pipeline: ' + pipeline.name, context }
  context.push({ kind: 'dashboard', dashboard_id: dashboard.id, ...(dashboard.slot ? { slot: dashboard.slot } : {}) })
  const where = dashboard.slot ? dashboard.name + ', slot “' + dashboard.slot + '”' : dashboard.name + ', a new slot'
  return {
    key: 'pipeline:' + pipeline.operator_id + '@' + dashboard.id + ':' + (dashboard.slot ?? ''),
    label: 'Pipeline: ' + pipeline.name + ' → ' + where,
    context,
  }
}

/** The chip "Talk about this widget" puts on the message: the widget itself. */
export function widgetChip(widget: Pick<Widget, 'id' | 'title'>): Chip {
  return {
    key: 'widget:' + widget.id,
    label: 'Widget: ' + (widget.title || 'Untitled widget'),
    context: [{ kind: 'widget', widget_id: widget.id }],
  }
}
