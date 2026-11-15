import type { ReactNode } from 'react'
import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from './frame'
import { LowerThird } from './LowerThird'
import { CHAT_FRAMES, ChatScene } from './scenes/ChatScene'
import { Credits } from './scenes/Credits'
import { FeedbackLoop, LOOP_FRAMES } from './scenes/FeedbackLoop'

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

/** The pitch, three minutes, in the order of the story. Sections still planned show what
 * they will be; cases, timelines and trials wait for their branches to reach main. */
const SECTIONS: Section[] = [
  { name: 'Title', frames: s(4), scene: <Punch sub="Promoting better and equal cancer care">ada</Punch> },

  // 1. The analysis: how ADA got and integrated the data.
  { name: 'Ask', frames: CHAT_FRAMES, scene: <ChatScene /> },
  {
    name: 'Sources',
    frames: s(12),
    scene: (
      <Planned
        title="Open data, integrated in minutes"
        shows="Sotkanet, Statistics Finland, NORDCAN, the National Cancer Strategy PDF and the Espoo handout come in as sources, each with its address, fetch time and licence; PDFs are read with Context.dev."
      />
    ),
  },
  {
    name: 'Trace',
    frames: s(14),
    scene: (
      <Planned
        title="Every number traced to its source"
        shows="The survival chart draws itself; a click opens its pipeline: the transform's SQL, then the NORDCAN snapshot it read."
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
    frames: s(10),
    scene: (
      <Planned
        title="Equal care, county by county"
        shows="Breast screening by wellbeing services county on the map, referral delays, deaths against the 11,970 target."
      />
    ),
  },

  // 2. What the registries cannot tell.
  {
    name: 'Gaps',
    frames: s(29),
    scene: (
      <Planned
        title="Where the data runs out"
        shows="The data-quality dashboard: counties with no figures, indicators years out of date, no time to treatment per patient or per county, the education gap only in reports. Goal 3 cannot be measured with what exists."
      />
    ),
  },

  // 3. Cases fill the gap.
  {
    name: 'Cases',
    frames: s(30),
    scene: (
      <Planned
        title="Cases fill the gap"
        shows="Pathways › Cases: a clinician records a cancer case in a form generated from the case type; its steps (referral, diagnosis, treatment start) land on a timeline."
      />
    ),
  },

  // 4. What a case gives back: the patient's timeline and the trials it fits.
  {
    name: 'Timeline and trials',
    frames: s(35),
    scene: (
      <Planned
        title="A timeline for every patient, and the trials that fit"
        shows="The case page: the patient's pathway against the target times, delays flagged. The trial matcher runs on the case and its result sheet lists the recruiting trials that fit, from ClinicalTrials.gov."
      />
    ),
  },

  // 5. Why it lasts: the loop.
  { name: 'Loop', frames: LOOP_FRAMES, scene: <FeedbackLoop /> },

  { name: 'Credits', frames: s(13.5), scene: <Credits /> },
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
