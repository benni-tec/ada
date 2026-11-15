import type { ReactNode } from 'react'
import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from './frame'
import { LowerThird } from './LowerThird'
import { CHAT_FRAMES, ChatScene } from './scenes/ChatScene'
import { Credits } from './scenes/Credits'

/** One line of big type, punched in. */
function Punch({ children, sub }: { children: string; sub?: string }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const pop = spring({ frame, fps, config: { damping: 14, stiffness: 180 }, durationInFrames: 12 })
  return (
    <AbsoluteFill className="dark items-center justify-center bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif" }}>
      <div style={{ fontSize: 150, fontWeight: 800, letterSpacing: -4, transform: `scale(${0.85 + pop * 0.15})`, opacity: pop }}>{children}</div>
      {sub && (
        <div style={{ fontSize: 46, marginTop: 12, opacity: interpolate(frame, [8, 14], [0, 0.75], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
          {sub}
        </div>
      )}
    </AbsoluteFill>
  )
}

/** A screen of the app, drifting in. */
function Screen({ src, title, line }: { src: string; title: string; line: string }) {
  const frame = useCurrentFrame()
  const scale = interpolate(frame, [0, s(6)], [1.02, 1.2])
  return (
    <AbsoluteFill className="bg-black">
      <Img src={staticFile(src)} style={{ width: '100%', transform: `scale(${scale})`, transformOrigin: '70% 45%' }} />
      <LowerThird title={title} line={line} />
    </AbsoluteFill>
  )
}

/** A scene that is planned but not built yet: what it will show, at its length. */
function Planned({ title, shows }: { title: string; shows: string }) {
  return (
    <AbsoluteFill className="dark bg-background text-foreground">
      <div style={{ position: 'absolute', top: 96, left: 96, fontFamily: 'monospace', fontSize: 26, color: '#a78bfa' }}>PLANNED SCENE</div>
      <div style={{ position: 'absolute', top: 150, left: 96, right: 96, fontSize: 40, lineHeight: 1.4, color: 'rgba(255,255,255,0.6)' }}>{shows}</div>
      <LowerThird title={title} />
    </AbsoluteFill>
  )
}

type Section = { name: string; frames: number; scene: ReactNode }

/** The pitch, three minutes, in order. Sections still planned show what they will be. */
const SECTIONS: Section[] = [
  { name: 'Deaths', frames: s(2.5), scene: <Punch sub="cancer deaths a year in Finland">13,300</Punch> },
  { name: 'Unequal', frames: s(2.5), scene: <Punch sub="and survival depends on where you live">Not equal</Punch> },
  { name: 'Goal 3', frames: s(3), scene: <Punch sub="National Cancer Strategy 2026–2035">Goal 3</Punch> },
  {
    name: 'Problem',
    frames: s(16),
    scene: (
      <Planned
        title="The data is there, the answers are not"
        shows="Sotkanet, Statistics Finland, NORDCAN, the Cancer Registry's PDFs and the strategy itself fly in as cards; a spreadsheet chain no one can trace collapses."
      />
    ),
  },
  { name: 'Title', frames: s(3), scene: <Punch sub="traceable data analysis">ada</Punch> },
  { name: 'Ask', frames: CHAT_FRAMES, scene: <ChatScene /> },
  {
    name: 'Widget',
    frames: s(13.5),
    scene: (
      <Planned
        title="The answer is a chart, not a sentence"
        shows="The survival chart the agent made draws itself in the session (the real chart widget with NORDCAN rows): Finland against the Nordic level, the gap widening since 2005."
      />
    ),
  },
  {
    name: 'Trace',
    frames: s(22),
    scene: (
      <Planned
        title="Click a number, see where it came from"
        shows="The pipeline dialog: chart, then the transform's SQL, then the NORDCAN snapshot with its fetch time and address. Every step can be inspected and re-run."
      />
    ),
  },
  {
    name: 'Dashboard',
    frames: s(6),
    scene: <Screen src="session.png" title="Goal 3 on one dashboard" line="Survival gap, mortality against target, screening by county" />,
  },
  {
    name: 'Dashboard detail',
    frames: s(19),
    scene: (
      <Planned
        title="Equal care, county by county"
        shows="The Goal 3 dashboard's widgets one by one: breast screening by wellbeing services county on the map, referral delays, deaths against the 11,970 target."
      />
    ),
  },
  {
    name: 'Research',
    frames: s(22),
    scene: (
      <Planned
        title="It finds the data you do not have"
        shows="The research agent searches the web, reads the strategy PDF and the Espoo handout, and registers each table as a source with its provenance."
      />
    ),
  },
  {
    name: 'Judges',
    frames: s(16),
    scene: (
      <Planned
        title="A second model checks every figure"
        shows="A text widget's sentence with a figure; the judge's badge turns green, or flags the number it cannot find in the data. Custom widget code is checked for data written into it."
      />
    ),
  },
  {
    name: 'Alerts',
    frames: s(16),
    scene: (
      <Planned
        title="It keeps watching"
        shows="A county drops below 80 % screening: the alert bell turns yellow, and the session the rule is attached to gets the alert."
      />
    ),
  },
  {
    name: 'Impact',
    frames: s(16),
    scene: (
      <Planned
        title="From a dashboard to a decision"
        shows="What it means for Goal 3: one place where THL, wellbeing services counties and AstraZeneca can see the same traceable numbers, and ask the next question."
      />
    ),
  },
  { name: 'Close', frames: s(3.5), scene: <Punch sub="equal care, measured">ada</Punch> },
  { name: 'Credits', frames: s(12.5), scene: <Credits /> },
]

export const PITCH_FRAMES = SECTIONS.reduce((total, section) => total + section.frames, 0)

export function Pitch() {
  let at = 0
  return (
    <AbsoluteFill className="bg-black">
      {SECTIONS.map((section) => {
        const from = at
        at += section.frames
        return (
          <Sequence key={section.name} name={section.name} from={from} durationInFrames={section.frames}>
            {section.scene}
          </Sequence>
        )
      })}
    </AbsoluteFill>
  )
}
