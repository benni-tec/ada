import type { ReactNode } from 'react'
import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from './frame'
import { LowerThird } from './LowerThird'
import { CASES_FRAMES, CasesScene } from './scenes/CasesScene'
import { CHAT_FRAMES, ChatScene } from './scenes/ChatScene'
import { Credits } from './scenes/Credits'
import { FeedbackLoop, LOOP_FRAMES } from './scenes/FeedbackLoop'
import { SIDE_CHALLENGE_FRAMES, SideChallenges } from './scenes/SideChallenges'
import { TitleCard } from './scenes/TitleCard'

/** One line of big type, punched in. */
function Punch({ children, sub }: { children: string; sub?: string }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const pop = spring({ frame, fps, config: { damping: 14, stiffness: 180 }, durationInFrames: 12 })
  return (
    <AbsoluteFill className="items-center justify-center bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif" }}>
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
  const scale = interpolate(frame, [0, s(4)], [1.02, 1.16])
  return (
    <AbsoluteFill className="bg-background">
      <Img src={staticFile(src)} style={{ width: '100%', transform: `scale(${scale})`, transformOrigin: '70% 45%' }} />
      <LowerThird title={title} line={line} />
    </AbsoluteFill>
  )
}

/** A scene that is planned but not built yet: what it will show, at its length. */
function Planned({ title, shows }: { title: string; shows: string }) {
  return (
    <AbsoluteFill className="bg-background text-foreground">
      <div style={{ position: 'absolute', top: 96, left: 96, fontFamily: 'monospace', fontSize: 26, color: '#7c3aed' }}>PLANNED SCENE</div>
      <div style={{ position: 'absolute', top: 150, left: 96, right: 96, fontSize: 40, lineHeight: 1.4, color: 'var(--muted-foreground)' }}>{shows}</div>
      <LowerThird title={title} />
    </AbsoluteFill>
  )
}

type Section = { name: string; frames: number; scene: ReactNode }

/** The pitch, two minutes, in the order of the story: the case and its models first,
 * then where their data comes from, then the cases as data, which closes the loop. */
const SECTIONS: Section[] = [
  { name: 'Title', frames: s(3.5), scene: <TitleCard subtitle="Promoting better and equal cancer care" /> },
  { name: 'No clock', frames: s(3.5), scene: <Punch sub="Finland has no trigger, no clock and no measurement">No clock</Punch> },

  // 1. The central tool: cases with models.
  { name: 'Cases', frames: CASES_FRAMES, scene: <CasesScene /> },
  {
    name: 'Trials',
    frames: s(6),
    scene: (
      <Planned
        title="And the trials worth discussing"
        shows="The trial matcher on the same case: recruiting Nordic trials matched on cancer group, sex and age, Finnish sites first, then the nearest site from the case's county."
      />
    ),
  },

  // 2. Where the models' data comes from: ADA's analysis.
  { name: 'Data', frames: s(2), scene: <Punch sub="where the models' data comes from">The data</Punch> },
  { name: 'Ask', frames: CHAT_FRAMES, scene: <ChatScene /> },
  {
    name: 'Sources',
    frames: s(8),
    scene: (
      <Planned
        title="Open data, integrated in minutes"
        shows="Sotkanet, Statistics Finland, NORDCAN, ClinicalTrials.gov, the National Cancer Strategy PDF and the Espoo handout come in as sources, each with its address, fetch time and licence."
      />
    ),
  },
  {
    name: 'Trace',
    frames: s(8),
    scene: (
      <Planned
        title="Every number traced to its source"
        shows="A chart draws itself; a click opens its pipeline: the transform's SQL, then the snapshot it read."
      />
    ),
  },
  {
    name: 'Dashboard',
    frames: s(4),
    scene: <Screen src="dashboard-light.png" title="Goal 3 on one dashboard" line="Survival gap, mortality against target, screening by county" />,
  },
  {
    name: 'Evidence',
    frames: s(6),
    scene: (
      <Planned
        title="The model's figures cite their papers"
        shows="The pathway model's card: the Nordic standard times, Finnish education effects (Zai 2025) and delay effects (Hanna 2020), each with the passage it was read from."
      />
    ),
  },

  // 3. The gaps, and the cases that fill them.
  {
    name: 'Gaps',
    frames: s(8),
    scene: (
      <Planned
        title="Where open data stops"
        shows="The data-quality dashboard: counties with no figures, indicators years old, no time per pathway step anywhere in Finland."
      />
    ),
  },
  {
    name: 'Cases as data',
    frames: s(12),
    scene: (
      <Planned
        title="The cases are data too"
        shows="The cases become a source: share within target per county and step, median days, the bottleneck step, and an alert when a step slips."
      />
    ),
  },

  // 4. The loop: why it lasts.
  { name: 'Loop', frames: LOOP_FRAMES, scene: <FeedbackLoop /> },

  // 5. What it is built with: the side challenges.
  { name: 'Side challenges', frames: SIDE_CHALLENGE_FRAMES, scene: <SideChallenges /> },

  { name: 'Credits', frames: s(7.5), scene: <Credits /> },
]

export const PITCH_FRAMES = SECTIONS.reduce((total, section) => total + section.frames, 0)

export function Pitch() {
  let at = 0
  return (
    <AbsoluteFill className="bg-background">
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
