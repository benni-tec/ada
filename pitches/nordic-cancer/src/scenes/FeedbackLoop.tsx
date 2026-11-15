import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'

import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** The loop, clockwise from the top: what each side puts in and gets back. */
const STEPS = [
  { title: 'Clinicians enter cases', line: 'referral, diagnosis, treatment' },
  { title: 'They get answers back', line: 'the patient’s timeline, matching trials' },
  { title: 'Cases become data', line: 'live waiting times per county' },
  { title: 'The gaps close', line: 'equal care, measured, for everyone' },
]

const CENTER = { x: 960, y: 440 }
const RADIUS = 260
const EACH = s(3.5)

export const LOOP_FRAMES = s(18)

function position(index: number) {
  const angle = -Math.PI / 2 + (index * Math.PI) / 2
  return { x: CENTER.x + RADIUS * Math.cos(angle), y: CENTER.y + RADIUS * Math.sin(angle) }
}

/** The win-win: data is entered because whoever enters it gets something back. */
export function FeedbackLoop() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  // The arc of the loop drawn so far, a quarter per step.
  const drawn = interpolate(frame, [s(0.3), s(0.3) + EACH * STEPS.length], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const circumference = 2 * Math.PI * RADIUS
  return (
    <AbsoluteFill className="dark bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif" }}>
      <svg width={1920} height={1080} style={{ position: 'absolute' }}>
        <circle cx={CENTER.x} cy={CENTER.y} r={RADIUS} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={6} />
        <circle
          cx={CENTER.x}
          cy={CENTER.y}
          r={RADIUS}
          fill="none"
          stroke="#7c3aed"
          strokeWidth={6}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - drawn)}
          transform={`rotate(-90 ${CENTER.x} ${CENTER.y})`}
        />
      </svg>
      <div style={{ position: 'absolute', left: CENTER.x - 200, top: CENTER.y - 60, width: 400, textAlign: 'center' }}>
        <div style={{ fontSize: 84, fontWeight: 800, letterSpacing: -2 }}>ada</div>
        <div style={{ fontSize: 26, color: 'rgba(255,255,255,0.6)' }}>win-win</div>
      </div>
      {STEPS.map((step, index) => {
        const at = s(0.3) + index * EACH
        const pop = spring({ frame: frame - at, fps, config: { damping: 16, stiffness: 200 }, durationInFrames: 12 })
        const { x, y } = position(index)
        const left = index === 3
        const right = index === 1
        return (
          <div
            key={step.title}
            style={{
              position: 'absolute',
              left: left ? x - 520 : right ? x + 36 : x - 260,
              top: index === 0 ? y - 150 : index === 2 ? y + 40 : y - 48,
              width: 500,
              textAlign: left ? 'right' : right ? 'left' : 'center',
              opacity: pop,
              transform: `scale(${0.9 + pop * 0.1})`,
            }}
          >
            <div style={{ fontSize: 44, fontWeight: 700 }}>{step.title}</div>
            <div style={{ fontSize: 28, color: 'rgba(255,255,255,0.65)', marginTop: 4 }}>{step.line}</div>
          </div>
        )
      })}
      {STEPS.map((step, index) => {
        const { x, y } = position(index)
        const lit = frame >= s(0.3) + index * EACH
        return (
          <div
            key={`dot-${step.title}`}
            style={{
              position: 'absolute',
              left: x - 16,
              top: y - 16,
              width: 32,
              height: 32,
              borderRadius: 16,
              background: lit ? '#7c3aed' : '#27272a',
              boxShadow: lit ? '0 0 24px #7c3aed' : 'none',
            }}
          />
        )
      })}
      {frame >= s(0.3) + EACH * STEPS.length && (
        <LowerThird title="Data is entered because entering it pays off" line="Clinicians, patients and analysts all win" accent="#22c55e" />
      )}
    </AbsoluteFill>
  )
}
