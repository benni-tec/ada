import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion'

import { Cursor } from '../Cursor'
import { s } from '../frame'
import { LowerThird } from '../LowerThird'

/** The dashboard built in ADA on the cases source (a screenshot of the app, light mode). */
const IMAGE = 'cases-dashboard.png'

/** Camera stops: scale and offset of the screenshot, at frame `at`. */
const CAMERA = [
  { at: 0, scale: 1, x: 0, y: 0 },
  { at: s(3.6), scale: 1.04, x: -20, y: -10 },
  // The county chart.
  { at: s(4.5), scale: 1.45, x: -478, y: -540 },
  { at: s(8.6), scale: 1.47, x: -486, y: -548 },
  // The steps chart and its bottleneck.
  { at: s(9.5), scale: 1.45, x: -903, y: -520 },
  { at: s(14), scale: 1.48, x: -930, y: -532 },
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

export const CASES_DATA_FRAMES = s(14)

/** The cases are data too: county by county, step by step, as they are entered. */
export function CasesDataScene() {
  const frame = useCurrentFrame()
  const { scale, x, y } = camera(frame)
  return (
    <AbsoluteFill className="overflow-hidden bg-background">
      <Img src={staticFile(IMAGE)} style={{ width: 1920, transformOrigin: '0 0', transform: `translate(${x}px, ${y}px) scale(${scale})` }} />
      <Cursor
        path={[
          { at: s(0.6), x: 1700, y: 1000 },
          { at: s(2.6), x: 1300, y: 640 },
          { at: s(5.6), x: 1053, y: 240 },
          { at: s(10.6), x: 1579, y: 392 },
        ]}
      />
      <Sequence durationInFrames={s(4.2)}>
        <LowerThird title="The cases are data too" line="Read like any other source, as they are entered (synthetic data)" exitAt={s(3.8)} />
      </Sequence>
      <Sequence from={s(4.5)} durationInFrames={s(4.8)}>
        <LowerThird title="Who waits longest" line="Days behind the treatment-start target, county by county" accent="#f97316" exitAt={s(4.4)} />
      </Sequence>
      <Sequence from={s(9.5)}>
        <LowerThird title="The bottleneck step" line="Specialist to work-up takes longest: where to act first" accent="#dc2626" />
      </Sequence>
    </AbsoluteFill>
  )
}
