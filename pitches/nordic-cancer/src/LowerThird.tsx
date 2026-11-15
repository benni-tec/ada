import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'

/**
 * A caption as television names a speaker: a square banner at the bottom left with a thin
 * strip of colour on its left edge. It slides in, holds, and slides out by `exitAt`.
 */
export function LowerThird({
  title,
  line,
  accent = '#7c3aed',
  exitAt,
}: {
  title: string
  line?: string
  accent?: string
  exitAt?: number
}) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 10 })
  const leave = exitAt === undefined ? 0 : spring({ frame: frame - exitAt, fps, config: { damping: 200 }, durationInFrames: 8 })
  const shown = enter - leave
  return (
    <div
      style={{
        position: 'absolute',
        left: 96,
        bottom: 88,
        display: 'flex',
        transform: `translateX(${(1 - shown) * -120}px)`,
        opacity: shown,
        fontFamily: "'Geist Variable', sans-serif",
      }}
    >
      <div style={{ width: 12, background: accent }} />
      <div style={{ background: 'white', color: '#0a0a0e', padding: '18px 34px 20px 26px', boxShadow: '0 12px 40px rgba(0,0,0,0.35)' }}>
        <div style={{ fontSize: 44, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1.1 }}>{title}</div>
        {line && (
          <div
            style={{
              fontSize: 28,
              marginTop: 6,
              color: 'rgba(10,10,14,0.65)',
              opacity: interpolate(frame, [4, 10], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }),
            }}
          >
            {line}
          </div>
        )}
      </div>
    </div>
  )
}
