import { Easing, interpolate, useCurrentFrame } from 'remotion'

/** Where the pointer is at frame `at`; `click` presses there. */
export type Point = { at: number; x: number; y: number; click?: boolean }

const CLICK = 12

/**
 * A mouse pointer that draws the eye: it glides between points (eased), holds between them,
 * and shows a ripple where it clicks. Coordinates are the video's pixels (1920 x 1080).
 */
export function Cursor({ path }: { path: readonly Point[] }) {
  const frame = useCurrentFrame()
  const next = path.findIndex((point) => point.at > frame)
  const to = next === -1 ? path[path.length - 1] : path[next]
  const from = next <= 0 ? to : path[next - 1]
  // Each move takes the last 40 % of the time to the next point, so the pointer rests first.
  const start = from.at + (to.at - from.at) * 0.6
  const t = from === to ? 1 : interpolate(frame, [start, to.at], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic) })
  const x = from.x + (to.x - from.x) * t
  const y = from.y + (to.y - from.y) * t
  const clicked = [...path].reverse().find((point) => point.click && frame >= point.at && frame < point.at + CLICK)
  const pressed = clicked ? interpolate(frame - clicked.at, [0, 3, 8], [1, 0.85, 1], { extrapolateRight: 'clamp' }) : 1
  const appear = interpolate(frame, [path[0].at, path[0].at + 6], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <>
      {clicked && (
        <div
          style={{
            position: 'absolute',
            left: clicked.x - 40,
            top: clicked.y - 40,
            width: 80,
            height: 80,
            borderRadius: 40,
            border: '4px solid #7c3aed',
            transform: `scale(${interpolate(frame - clicked.at, [0, CLICK], [0.2, 1.2])})`,
            opacity: interpolate(frame - clicked.at, [0, CLICK], [0.9, 0]),
          }}
        />
      )}
      <svg
        width={44}
        height={44}
        viewBox="0 0 24 24"
        style={{ position: 'absolute', left: x - 6, top: y - 3, transform: `scale(${pressed})`, transformOrigin: '6px 3px', opacity: appear, filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.3))' }}
      >
        <path d="M5.5 3.2 L5.5 19.8 L10 15.6 L13 21.8 L15.9 20.5 L12.9 14.4 L19 14.4 Z" fill="#0a0a0e" stroke="white" strokeWidth={1.4} strokeLinejoin="round" />
      </svg>
    </>
  )
}
