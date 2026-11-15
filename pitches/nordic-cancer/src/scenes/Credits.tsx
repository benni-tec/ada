import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion'

import { COPYRIGHT, DATA_CREDITS, DISCLAIMER, EVENT, TEAM } from '../team'

const fade = (frame: number, start: number) =>
  interpolate(frame, [start, start + 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

/** The last card: who made it, whose data it shows, and the copyright notice. */
export function Credits() {
  const frame = useCurrentFrame()
  const year = 2026
  return (
    <AbsoluteFill className="dark bg-background text-foreground" style={{ fontFamily: "'Geist Variable', sans-serif", padding: '120px 160px' }}>
      <div style={{ fontSize: 120, fontWeight: 800, letterSpacing: -4, opacity: fade(frame, 0) }}>ada</div>
      <div style={{ fontSize: 40, color: 'rgba(255,255,255,0.7)', marginTop: 4, opacity: fade(frame, 4) }}>Traceable data analysis</div>
      <div style={{ display: 'flex', gap: 40, marginTop: 72, fontSize: 42, fontWeight: 600, whiteSpace: 'nowrap', opacity: fade(frame, 10) }}>
        {TEAM.map((name) => (
          <div key={name} style={{ borderLeft: '8px solid #7c3aed', paddingLeft: 20 }}>
            {name}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 30, color: 'rgba(255,255,255,0.7)', marginTop: 28, opacity: fade(frame, 14) }}>{EVENT}</div>
      <div style={{ marginTop: 'auto', fontSize: 22, lineHeight: 1.5, color: 'rgba(255,255,255,0.55)', opacity: fade(frame, 20) }}>
        <div>Data: {DATA_CREDITS.join(' · ')}</div>
        <div style={{ marginTop: 8 }}>
          © {year} {COPYRIGHT.join(', ')}. {DISCLAIMER}
        </div>
      </div>
    </AbsoluteFill>
  )
}
