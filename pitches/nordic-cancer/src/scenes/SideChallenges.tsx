import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** The side challenges the project takes part in, and what it uses each one for. */
const CHALLENGES = [
  {
    name: 'Context.dev',
    challenge: 'Best Use of Context.dev: Fully Structured Web',
    use: 'PDFs, tables and web pages become sources with provenance; search, page monitors and the research agent read through it.',
    accent: '#f97316',
  },
  {
    name: 'Gemini API',
    challenge: 'Best Use of Gemini API',
    use: 'The analyst agent, the research agent and the judges that check every figure run on Gemini.',
    accent: '#3b82f6',
  },
  {
    name: 'Verda',
    challenge: 'Verda Compute Track',
    use: 'ADA runs on a Verda VM, deployed from CI on every push to main.',
    accent: '#22c55e',
  },
]

export const SIDE_CHALLENGE_FRAMES = s(10)

export function SideChallenges() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return (
    <AbsoluteFill className="bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif", padding: '140px 120px 0' }}>
      <div style={{ display: 'flex', gap: 40 }}>
        {CHALLENGES.map((item, index) => {
          const pop = spring({ frame: frame - s(0.3) - index * s(0.6), fps, config: { damping: 16, stiffness: 200 }, durationInFrames: 12 })
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
              <div style={{ background: 'var(--muted)', padding: '36px 36px 40px', flex: 1 }}>
                <div style={{ fontSize: 60, fontWeight: 800, letterSpacing: -1.5 }}>{item.name}</div>
                <div style={{ fontSize: 26, color: item.accent, marginTop: 8, fontWeight: 600 }}>{item.challenge}</div>
                <div style={{ fontSize: 30, lineHeight: 1.45, color: 'var(--muted-foreground)', marginTop: 28 }}>{item.use}</div>
              </div>
            </div>
          )
        })}
      </div>
      <LowerThird title="Side challenges" line="Junction 2026" />
    </AbsoluteFill>
  )
}
