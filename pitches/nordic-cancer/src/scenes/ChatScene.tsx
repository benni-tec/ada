import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion'

import { AgentTurnView } from '@/components/chat/agent-turn'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Message, MessageContent } from '@/components/ui/message'
import { TooltipProvider } from '@/components/ui/tooltip'

import { Cursor } from '../Cursor'
import { s } from '../frame'
import { LowerThird } from '../LowerThird'
import { turnAt, type Step } from '../stream'

const QUESTION = 'Where does Finland fall behind the Nordic level in cancer survival?'

const NORDCAN = 'https://canapi.iarc.who.int/api/nordcan/v2/961/survival/population/5/1_2/208_246_578_752/110_130_160/'

const STEPS: Step[] = [
  { at: s(1.1), kind: 'reasoning', text: 'Compare five-year survival in Finland with Sweden and Norway, per cancer.', for: s(0.4) },
  {
    at: s(1.5),
    kind: 'tool',
    name: 'search_web',
    input: { query: 'NORDCAN five-year survival Nordic countries', scope: 'data' },
    output: { results: [{ title: 'NORDCAN: cancer survival in the Nordic countries', url: 'https://nordcan.iarc.fr' }] },
    for: s(0.5),
  },
  {
    at: s(2.1),
    kind: 'tool',
    name: 'register_source',
    input: { name: 'Five-year survival, Nordic countries (NORDCAN)', address: NORDCAN },
    output: { data_source: { name: 'Five-year survival, Nordic countries (NORDCAN)' }, snapshot: { rows: 312 } },
    for: s(0.5),
  },
  {
    at: s(2.7),
    kind: 'tool',
    name: 'add_transform',
    input: { sql: 'SELECT cancer, year, finland, (sweden + norway) / 2 AS nordic FROM input_0' },
    output: { operator: { kind: 'transform', columns: ['cancer', 'year', 'finland', 'nordic'] } },
    for: s(0.4),
  },
  {
    at: s(3.2),
    kind: 'tool',
    name: 'create_widget',
    input: { type: 'chart', title: 'Five-year survival: Finland against the Nordic level' },
    output: { widget: { type: 'chart' }, url: '/projects/nordic/widgets/survival' },
    for: s(0.4),
  },
  {
    at: s(3.7),
    kind: 'text',
    text:
      'Finland trails the Nordic level for every poor-prognosis cancer, and the gap has **widened since 2005**. ' +
      'The chart shows it; every point links back to NORDCAN.',
    charsPerFrame: 5,
  },
]

export const CHAT_FRAMES = s(6.5)

/** The question, then the agent at work: the app's own chat, streamed from a script. */
export function ChatScene() {
  const frame = useCurrentFrame()
  const typed = QUESTION.slice(0, Math.floor(frame * 3.2))
  return (
    <AbsoluteFill className="bg-background text-foreground">
      <TooltipProvider>
        <div className="flex h-full flex-col justify-end px-[13%] pb-[150px]" style={{ zoom: 2.3 }}>
          <div className="flex flex-col gap-5">
            <Message align="end">
              <MessageContent className="gap-1.5">
                <Bubble align="end" variant="secondary">
                  <BubbleContent className="whitespace-pre-wrap">{typed}</BubbleContent>
                </Bubble>
              </MessageContent>
            </Message>
            {frame >= s(1) && <AgentTurnView turn={turnAt(STEPS, frame)} />}
          </div>
        </div>
      </TooltipProvider>
      {/* The newest tool row stays at one height, since the chat grows upwards. */}
      <Cursor
        path={[
          { at: s(0.2), x: 1650, y: 980 },
          { at: s(1.4), x: 560, y: 712 },
          { at: s(3.7), x: 560, y: 712 },
          { at: s(4.4), x: 1560, y: 860 },
        ]}
      />
      <Sequence durationInFrames={s(1.4)}>
        <LowerThird title="Ask in plain language" line="ADA works on Finland's open health data" exitAt={s(1.1)} />
      </Sequence>
      <Sequence from={s(1.5)} durationInFrames={s(2.4)}>
        <LowerThird title="It builds a pipeline, not an answer" line="Sources, SQL and charts you can inspect" exitAt={s(2.1)} />
      </Sequence>
      <Sequence from={s(4)}>
        <LowerThird title="No number passes through the model" line="Widgets read the data themselves" accent="#22c55e" />
      </Sequence>
    </AbsoluteFill>
  )
}
