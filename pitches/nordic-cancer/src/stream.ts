import type { AgentTurn, Part } from '@/lib/api'

/** One step of a scripted turn, appearing at `at` (frames into the scene). */
export type Step =
  | { at: number; kind: 'reasoning'; text: string; for: number }
  | { at: number; kind: 'tool'; name: string; input: Record<string, unknown>; output: unknown; for: number }
  | { at: number; kind: 'text'; text: string; charsPerFrame: number }

/**
 * The agent's turn as it stands at `frame`: steps that started are shown, a tool is
 * running until its time is up, and text streams in at its speed. No agent runs: the
 * video shows a scripted conversation through the app's own components.
 */
export function turnAt(steps: readonly Step[], frame: number): AgentTurn {
  const parts: Part[] = []
  let running = false
  for (const step of steps) {
    if (frame < step.at) break
    const elapsed = frame - step.at
    if (step.kind === 'reasoning') {
      parts.push({ type: 'reasoning', text: step.text })
      running ||= elapsed < step.for
    } else if (step.kind === 'tool') {
      const done = elapsed >= step.for
      parts.push({
        type: 'tool',
        tool_call_id: `${step.name}-${step.at}`,
        tool_name: step.name,
        input: step.input,
        output: done ? step.output : undefined,
        state: done ? 'output-available' : 'input-available',
      })
      running ||= !done
    } else {
      const shown = Math.min(step.text.length, Math.floor(elapsed * step.charsPerFrame))
      parts.push({ type: 'text', text: step.text.slice(0, shown) })
      running ||= shown < step.text.length
    }
  }
  const last = steps[steps.length - 1]
  const finished = last !== undefined && frame >= last.at && !running
  return {
    id: 'turn',
    session_id: 'session',
    prompt_entry_id: 'prompt',
    model: 'gemini/gemini-3-pro',
    created_at: '2026-11-15T09:00:00Z',
    status: finished ? 'done' : 'running',
    parts,
  }
}
