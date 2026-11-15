import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion'

import { Cursor } from '../Cursor'
import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** Screenshots of the "National Cancer Strategy 2026–2035" dashboard in ADA, light mode: the
 * whole page (a tall viewport), and its top with the bell opened on the active alerts. Both
 * are 1400 CSS px wide, shown 1920 wide. */
const PAGE = 'goals-full.png'
const ALERTS = 'goals-alerts.png'

// One goal band per row of the dashboard, 1.15 times larger, its cards centred.
const ZOOM = 1.15
const X = -346
const band = (top: number) => -(top * ZOOM - 98)
const GOAL1 = band(398)
const GOAL2 = band(1188)
const GOAL3 = band(1978)
const GOAL3_MORE = band(2768)
const GOAL4 = band(3557)

const CLICK = s(9.8)

const CAMERA = [
  { at: 0, scale: 1, x: 0, y: 0 },
  { at: s(1.1), scale: 1, x: 0, y: 0 },
  { at: s(1.7), scale: ZOOM, x: X, y: GOAL1 },
  { at: s(3.1), scale: ZOOM, x: X, y: GOAL1 },
  { at: s(3.7), scale: ZOOM, x: X, y: GOAL2 },
  { at: s(5.1), scale: ZOOM, x: X, y: GOAL2 },
  { at: s(5.7), scale: ZOOM, x: X, y: GOAL3 },
  { at: s(6.7), scale: ZOOM, x: X, y: GOAL3 },
  { at: s(7.2), scale: ZOOM, x: X, y: GOAL3_MORE },
  { at: s(7.9), scale: ZOOM, x: X, y: GOAL3_MORE },
  { at: s(8.4), scale: ZOOM, x: X, y: GOAL4 },
  { at: s(9.1), scale: ZOOM, x: X, y: GOAL4 },
  // Back to the top for the bell, then into the alert list.
  { at: s(9.4), scale: 1, x: 0, y: 0 },
  { at: CLICK + s(0.4), scale: 1, x: 0, y: 0 },
  { at: CLICK + s(1), scale: 1.6, x: -878, y: -300 },
  { at: s(12), scale: 1.62, x: -890, y: -306 },
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

const BANNERS = [
  { from: s(1.7), to: s(3.5), title: 'Goal 1 · Human-centred services', line: "Each goal opens with the strategy's own targets" },
  { from: s(3.7), to: s(5.5), title: 'Goal 2 · Prevention and early detection', line: 'No county reaches 80 % in all three screenings', accent: '#f97316' },
  { from: s(5.7), to: s(8.2), title: 'Goal 3 · Equal and effective care', line: '1,346 deaths a year above the target; pathway times from the cases', accent: '#dc2626' },
  { from: s(8.4), to: s(9.6), title: 'Goal 4 · Staying at the forefront', line: '6.3 trials per million against the Nordic 8.6', accent: '#2563eb' },
]

export const GOALS_FRAMES = s(12)

/** The four goals of the National Cancer Strategy, top to bottom, and the dashboard's alerts. */
export function GoalsScene() {
  const frame = useCurrentFrame()
  const { scale, x, y } = camera(frame)
  const transform = `translate(${x}px, ${y}px) scale(${scale})`
  const opened = interpolate(frame, [CLICK + 3, CLICK + 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill className="overflow-hidden bg-background">
      <Img src={staticFile(PAGE)} style={{ position: 'absolute', width: 1920, transformOrigin: '0 0', transform }} />
      <Img src={staticFile(ALERTS)} style={{ position: 'absolute', width: 1920, transformOrigin: '0 0', transform, opacity: opened }} />
      <Cursor
        path={[
          { at: s(0.6), x: 1500, y: 1000 },
          { at: s(2.6), x: 789, y: 524 },
          { at: s(4.6), x: 758, y: 546 },
          { at: s(6.4), x: 789, y: 537 },
          { at: s(8.9), x: 1373, y: 534 },
          { at: CLICK - 5, x: 1322, y: 239 },
          { at: CLICK, x: 1322, y: 239, click: true },
          { at: s(11.4), x: 960, y: 358 },
        ]}
      />
      <Sequence durationInFrames={s(1.6)}>
        <LowerThird title="National Cancer Strategy 2026–2035" line="Its four goals on one dashboard, top to bottom" exitAt={s(1.3)} />
      </Sequence>
      {BANNERS.map((banner) => (
        <Sequence key={banner.title} from={banner.from} durationInFrames={banner.to - banner.from}>
          <LowerThird title={banner.title} line={banner.line} accent={banner.accent} exitAt={banner.to - banner.from - s(0.3)} />
        </Sequence>
      ))}
      <Sequence from={CLICK + s(0.4)}>
        <LowerThird title="Alerts when a goal slips" line="Critical: cancer deaths above the 2035 target" accent="#dc2626" />
      </Sequence>
    </AbsoluteFill>
  )
}
