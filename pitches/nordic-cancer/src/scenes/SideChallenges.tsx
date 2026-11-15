import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** The side challenges the project takes part in, and the uses of each worth telling. */
const CHALLENGES = [
  {
    name: 'Context.dev',
    challenge: 'Best Use of Context.dev: Fully Structured Web',
    lead: ['The web as ', 'live, traceable sources'],
    uses: [
      "Nordic hospitals' trial pages, scraped and watched: a new trial listed in Finland raises an alert",
      'Their lists checked against the registry: trials one shows and the other misses',
      'Sponsor study pages turned into rows of Nordic sites by an instruction, null where a page is silent',
    ],
    accent: '#f97316',
  },
  {
    name: 'Gemini API',
    challenge: 'Best Use of Gemini API',
    lead: ['A judge that ', 'checks every figure'],
    uses: [
      "Gemini's decision model reads every text widget against the rows of its pipeline",
      'It flags a number typed in instead of drawn from the data, and a claim the rows contradict',
      'The analyst agent that builds the pipelines runs on Gemini too',
    ],
    accent: '#3b82f6',
  },
]

// The cards come in together; their uses one at a time, the left card's first, at reading pace.
const USES_FROM = [s(1), s(4.4)]
const USE_EVERY = s(1)

export const SIDE_CHALLENGE_FRAMES = s(10)

export function SideChallenges() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return (
    <AbsoluteFill className="bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif", padding: '120px 120px 0' }}>
      <div style={{ display: 'flex', gap: 40 }}>
        {CHALLENGES.map((item, index) => {
          const pop = spring({ frame: frame - s(0.2) - index * s(0.3), fps, config: { damping: 16, stiffness: 200 }, durationInFrames: 12 })
          return (
            <div
              key={item.name}
              style={{
                flex: 1,
                display: 'flex',
                opacity: pop,
                transform: `translateY(${(1 - pop) * 40}px)`,
              }}
            >
              <div style={{ width: 10, background: item.accent }} />
              <div style={{ background: 'var(--muted)', padding: '36px 40px 44px', flex: 1 }}>
                <div style={{ fontSize: 56, fontWeight: 800, letterSpacing: -1.5 }}>{item.name}</div>
                <div style={{ fontSize: 24, color: item.accent, marginTop: 6, fontWeight: 600 }}>{item.challenge}</div>
                <div style={{ fontSize: 42, fontWeight: 700, letterSpacing: -0.8, lineHeight: 1.15, marginTop: 30 }}>
                  {item.lead[0]}
                  <span style={{ color: item.accent }}>{item.lead[1]}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20, marginTop: 30 }}>
                  {item.uses.map((use, n) => {
                    const shown = spring({ frame: frame - USES_FROM[index] - n * USE_EVERY, fps, config: { damping: 18, stiffness: 160 }, durationInFrames: 14 })
                    return (
                      <div key={use} style={{ display: 'flex', gap: 18, opacity: shown, transform: `translateY(${(1 - shown) * 18}px)` }}>
                        <div style={{ width: 12, height: 12, marginTop: 14, flexShrink: 0, background: item.accent }} />
                        <div style={{ fontSize: 29, lineHeight: 1.4, color: 'var(--muted-foreground)' }}>{use}</div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <LowerThird title="Side challenges" line="Junction 2026" />
    </AbsoluteFill>
  )
}
