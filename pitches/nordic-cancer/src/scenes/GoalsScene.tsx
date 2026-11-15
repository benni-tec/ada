import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion'

import { Cursor } from '../Cursor'
import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** Screenshots of the "The strategy's four goals" dashboard in ADA, light mode: as it is,
 * and with its bell opened on the active alerts. */
const DASHBOARD = 'goals-dashboard.png'
const ALERTS = 'goals-alerts.png'

const CLICK = s(7)

const CAMERA = [
  { at: 0, scale: 1, x: 0, y: 0 },
  { at: s(3.2), scale: 1.03, x: -14, y: -8 },
  // The four goal tiles.
  { at: s(3.9), scale: 1.2, x: -443, y: -335 },
  { at: s(6), scale: 1.22, x: -456, y: -342 },
  // Back out, to the bell.
  { at: s(6.6), scale: 1, x: 0, y: 0 },
  { at: CLICK + s(0.6), scale: 1, x: 0, y: 0 },
  // The alert list, the critical one first.
  { at: CLICK + s(1.2), scale: 1.5, x: -1200, y: -128 },
  { at: s(11), scale: 1.52, x: -1222, y: -136 },
]

function camera(frame: number) {
  const at = CAMERA.map((stop) => stop.at)
  const ease = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic) } as const
  return {
    scale: interpolate(frame, at, CAMERA.map((stop) => stop.scale), ease),
    x: interpolate(frame, at, CAMERA.map((stop) => stop.x), ease),
    y: interpolate(frame, at, CAMERA.map((stop) => stop.y), ease),
  }
}

export const GOALS_FRAMES = s(11)

/** The four goals of the National Cancer Strategy on one dashboard, and its alerts. */
export function GoalsScene() {
  const frame = useCurrentFrame()
  const { scale, x, y } = camera(frame)
  const transform = `translate(${x}px, ${y}px) scale(${scale})`
  const opened = interpolate(frame, [CLICK + 3, CLICK + 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill className="overflow-hidden bg-background">
      <Img src={staticFile(DASHBOARD)} style={{ position: 'absolute', width: 1920, transformOrigin: '0 0', transform }} />
      <Img src={staticFile(ALERTS)} style={{ position: 'absolute', width: 1920, transformOrigin: '0 0', transform, opacity: opened }} />
      <Cursor
        path={[
          { at: s(0.8), x: 1500, y: 1000 },
          { at: s(5), x: 1077, y: 440 },
          { at: CLICK - 5, x: 1838, y: 117 },
          { at: CLICK, x: 1838, y: 117, click: true },
          { at: s(9), x: 1248, y: 222 },
        ]}
      />
      <Sequence durationInFrames={CLICK - s(0.4)}>
        <LowerThird title="The strategy's four goals, on one dashboard" line="Each goal against its target, from open data" exitAt={CLICK - s(0.8)} />
      </Sequence>
      <Sequence from={CLICK + s(0.4)}>
        <LowerThird title="Alerts when a goal slips" line="Critical: cancer deaths 1,346 above the 2035 target" accent="#dc2626" />
      </Sequence>
    </AbsoluteFill>
  )
}
