import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'

import { Vahti } from '@/components/vahti/vahti'

/** The opening card: Vahti, ADA's mascot, rises with its lantern beside the name. */
export function TitleCard({ subtitle }: { subtitle: string }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const rise = spring({ frame, fps, config: { damping: 13, stiffness: 140 }, durationInFrames: 18 })
  const text = spring({ frame: frame - 6, fps, config: { damping: 200 }, durationInFrames: 14 })
  // Vahti looks at the name once it is there.
  const look: [number, number] = [interpolate(frame, [18, 30], [0, 5], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }), 1]
  return (
    <AbsoluteFill className="items-center justify-center bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif" }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 56 }}>
        <div style={{ transform: `translateY(${(1 - rise) * 160}px)`, opacity: Math.min(1, rise * 1.5) }}>
          <Vahti pose="watching" size={300} label="" look={look} />
        </div>
        <div style={{ opacity: text, transform: `translateX(${(1 - text) * 40}px)` }}>
          <div style={{ fontSize: 200, fontWeight: 800, letterSpacing: -8, lineHeight: 0.9 }}>ada</div>
          <div style={{ fontSize: 46, marginTop: 18, color: 'var(--muted-foreground)', whiteSpace: 'nowrap' }}>{subtitle}</div>
        </div>
      </div>
    </AbsoluteFill>
  )
}
