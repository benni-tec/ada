import { useEffect, useId, useRef, useState, type RefObject } from 'react'

import './vahti.css'

/**
 * Vahti ("guard" in Finnish), the face of ADA's agent: an ink creature with a striped scarf
 * and a storm lantern. Ink is `currentColor` and paper is `--vahti-paper` (the page
 * background by default), so it turns light on dark by itself; the eyes stay light with dark
 * pupils on any body. It stays out of widgets, reports and alerts: it marks the agent working,
 * resting or puzzled, never a finding in the data.
 */
export type VahtiPose = 'watching' | 'searching' | 'asleep' | 'puzzled' | 'peek'

const LABEL: Record<VahtiPose, string> = {
  watching: 'Vahti keeping watch with a lantern',
  searching: 'Vahti holding the lantern out, looking',
  asleep: 'Vahti asleep, lantern out',
  puzzled: 'Vahti scratching its head',
  peek: 'Vahti peeking over the line',
}

const BODY = 'M61 27 C85 29 93 55 92 79 C91 101 79 113 59 112 C39 111 27 99 28 77 C29 55 37 26 61 27 Z'
const PEEK_BODY = 'M61 27 C85 29 93 55 92 79 L28 79 C29 55 37 26 61 27 Z'
const TUFT_L = 'M46 37 C42 27 37 21 29 19 C27 18 26 16 29 15 C39 15 49 22 55 31 Z'
const TUFT_R = 'M69 31 C72 20 77 11 85 8 C88 7 89 9 87 11 C82 17 80 27 77 37 Z'
const TUFT_L_DROOP = 'M45 38 C38 33 32 32 25 34 C33 29 42 28 51 32 Z'
const TUFT_R_DROOP = 'M73 33 C80 29 88 29 95 32 C88 34 81 36 76 39 Z'
const INK = 'currentColor'
const PAPER = 'var(--vahti-paper)'
const EYE = 'var(--vahti-eye)'
const line = { fill: 'none', stroke: INK, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

function Eyes({ look, shift }: { look: [number, number]; shift?: [number, number] }) {
  const [dx, dy] = look
  const eyes: [number, number, number, number][] = [
    [49, 62, 10, 12],
    [72, 60, 11, 13],
  ]
  return (
    <g className="v-eyes">
      {eyes.map(([cx, cy, rx, ry]) => (
        <ellipse key={cx} cx={cx} cy={cy} rx={rx} ry={ry} fill={EYE} stroke="var(--vahti-pupil)" strokeWidth={2} />
      ))}
      <g className="v-pupils" style={shift ? { transform: `translate(${shift[0]}px, ${shift[1]}px)` } : undefined}>
        {eyes.map(([cx, cy]) => (
          <g key={cx}>
            <circle cx={cx + dx} cy={cy + dy} r={4.6} fill="var(--vahti-pupil)" />
            <circle cx={cx + dx - 1.6} cy={cy + dy - 1.8} r={1.3} fill={EYE} />
          </g>
        ))}
      </g>
    </g>
  )
}

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** Pupil offset (in drawing units, at most 3.5) toward the pointer, once per frame. */
function usePointerLook(target: RefObject<SVGSVGElement | null>, on: boolean): [number, number] | undefined {
  const [shift, setShift] = useState<[number, number]>()
  useEffect(() => {
    if (!on || reducedMotion()) return
    let frame = 0
    const move = (event: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const box = target.current?.getBoundingClientRect()
        if (!box) return
        const x = event.clientX - (box.left + box.width / 2)
        const y = event.clientY - (box.top + box.height / 2)
        const length = Math.hypot(x, y) || 1
        const reach = Math.min(3.5, length / 40)
        setShift([(x / length) * reach, (y / length) * reach])
      })
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', move)
    }
  }, [target, on])
  return shift
}

function Legs() {
  return (
    <g {...line} strokeWidth={3}>
      <path d="M50 110 L48 124 L41 125.5" />
      <path d="M68 110 L70 124 L78 125" />
    </g>
  )
}

function Arm({ d }: { d: string }) {
  return <path d={d} {...line} strokeWidth={3} />
}

function Ground() {
  let d = ''
  for (let x = 30; x <= 92; x += 5) d += `M${x} 131 L${x + 5} 127 `
  return <path d={d} {...line} strokeWidth={1.3} />
}

function Scarf({ tail }: { tail: boolean }) {
  return (
    <g>
      <path d="M30 83 C45 90 75 90 91 81 L92 89 C76 98 45 98 29 91 Z" fill={PAPER} />
      <g stroke={INK} strokeWidth={1.6}>
        <path d="M38 86 L42 94" />
        <path d="M47 88 L51 96" />
        <path d="M56 89 L60 97" />
        <path d="M65 89 L69 97" />
        <path d="M74 88 L78 95" />
        <path d="M83 85 L86 92" />
      </g>
      {tail && (
        <g>
          <path d="M33 88 C27 96 22 104 17 112 L25 116 C29 108 34 100 40 92 Z" fill={PAPER} stroke={INK} strokeWidth={1.2} />
          <g stroke={INK} strokeWidth={1.6}>
            <path d="M26 99 L33 103" />
            <path d="M21 106 L28 110" />
          </g>
          <g {...line} strokeWidth={1.4}>
            <path d="M16 114 l-1 4" />
            <path d="M19 114 l-1 4" />
            <path d="M22 114 l-1 4" />
          </g>
        </g>
      )}
    </g>
  )
}

/** A storm lantern hanging from (x, y). */
function Lantern({ x, y, lit = true, rays = false }: { x: number; y: number; lit?: boolean; rays?: boolean }) {
  return (
    <g>
      <path d={`M${x - 4} ${y + 4} Q${x} ${y - 3} ${x + 4} ${y + 4}`} {...line} strokeWidth={1.8} />
      <path d={`M${x - 7} ${y + 7} L${x} ${y + 3} L${x + 7} ${y + 7} Z`} fill={INK} stroke={INK} strokeWidth={1.6} strokeLinejoin="round" />
      <path
        d={`M${x - 6.5} ${y + 7} C${x - 9} ${y + 13} ${x - 9} ${y + 20} ${x - 6.5} ${y + 25} L${x + 6.5} ${y + 25} C${x + 9} ${y + 20} ${x + 9} ${y + 13} ${x + 6.5} ${y + 7} Z`}
        fill={PAPER}
        stroke={INK}
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {lit ? (
        <path
          className="v-flame"
          style={{ transformOrigin: `${x}px ${y + 21}px` }}
          d={`M${x} ${y + 21} C${x - 3.5} ${y + 18} ${x - 1.5} ${y + 14} ${x} ${y + 11} C${x + 1.5} ${y + 14} ${x + 3.5} ${y + 18} ${x} ${y + 21} Z`}
          fill={INK}
        />
      ) : (
        <path d={`M${x} ${y + 2} c-2 -3 2 -5 0 -8 c-2 -3 2 -5 0 -7`} {...line} strokeWidth={1.2} />
      )}
      <path
        d={`M${x - 5} ${y + 8} C${x - 6.5} ${y + 13} ${x - 6.5} ${y + 19} ${x - 5} ${y + 24} M${x + 5} ${y + 8} C${x + 6.5} ${y + 13} ${x + 6.5} ${y + 19} ${x + 5} ${y + 24}`}
        {...line}
        strokeWidth={1.1}
      />
      <rect x={x - 8} y={y + 25} width={16} height={3.5} fill={INK} />
      {rays && (
        <g {...line} strokeWidth={1.8}>
          <path d={`M${x - 13} ${y + 17} l-6 0`} />
          <path d={`M${x + 13} ${y + 17} l6 0`} />
          <path d={`M${x - 11} ${y + 7} l-5 -4`} />
          <path d={`M${x + 11} ${y + 7} l5 -4`} />
          <path d={`M${x - 11} ${y + 27} l-5 4`} />
          <path d={`M${x + 11} ${y + 27} l5 4`} />
        </g>
      )}
    </g>
  )
}

function Head({ droop = false }: { droop?: boolean }) {
  return (
    <>
      <path d={droop ? TUFT_L_DROOP : TUFT_L} fill={INK} />
      <path d={droop ? TUFT_R_DROOP : TUFT_R} fill={INK} />
      <path d={BODY} fill={INK} />
    </>
  )
}

function Pose({ pose }: { pose: Exclude<VahtiPose, 'peek'> }) {
  switch (pose) {
    case 'watching':
      return (
        <>
          <Ground />
          <Legs />
          <Arm d="M33 88 Q26 95 29 101" />
          <Arm d="M89 80 Q99 86 101 94" />
          <Head />
          <Scarf tail />
          <Eyes look={[3.5, -1.5]} />
          <Lantern x={101} y={94} />
        </>
      )
    case 'searching':
      return (
        <>
          <Ground />
          <g transform="rotate(6 60 120)">
            <Legs />
            <Arm d="M33 86 Q27 94 30 100" />
            <Arm d="M88 76 Q100 72 108 68" />
            <Head />
            <Scarf tail />
            <Eyes look={[5, 1]} />
          </g>
          <g className="v-swing" style={{ transformOrigin: '110px 67px' }}>
            <Lantern x={110} y={67} rays />
          </g>
        </>
      )
    case 'asleep':
      return (
        <>
          <Ground />
          <g transform="translate(0 8) scale(1 0.96)">
            <Legs />
            <Arm d="M32 92 Q36 100 46 100" />
            <Arm d="M88 92 Q84 100 74 100" />
            <Head droop />
            <Scarf tail={false} />
            <g {...line} stroke={EYE} strokeWidth={2.6}>
              <path d="M40 64 Q49 70 58 64" />
              <path d="M62 62 Q72 68 82 62" />
            </g>
          </g>
          <Lantern x={104} y={98} lit={false} />
          <g className="v-z" {...line} strokeWidth={2}>
            <path d="M92 26 h8 l-8 9 h8" />
            <path d="M104 12 h6 l-6 7 h6" />
          </g>
        </>
      )
    case 'puzzled':
      return (
        <>
          <Ground />
          <g transform="rotate(-5 60 120)">
            <Legs />
            <Arm d="M33 88 Q26 95 29 101" />
            <Arm d="M89 74 Q100 58 84 40" />
            <path d={TUFT_L} fill={INK} />
            <path d={TUFT_R} fill={INK} transform="rotate(14 74 34)" />
            <path d={BODY} fill={INK} />
            <Scarf tail />
            <Eyes look={[-1.5, -5]} />
            <path d="M55 78 q3 -3 6 0 q3 3 6 0" {...line} stroke={EYE} strokeWidth={2} />
          </g>
          <path d="M100 14 c0 -6 10 -6 10 0 c0 4 -5 4 -5 9" {...line} strokeWidth={2.4} />
          <circle cx={105} cy={28.5} r={1.6} fill={INK} />
        </>
      )
  }
}

/**
 * `size` is the width in px. Pass `label=""` when the text next to it already says what
 * happens; it is then hidden from screen readers. `filter={false}` drops the ink wobble,
 * for small sizes where it would blur the edges.
 */
export function Vahti({
  pose,
  size = 120,
  label,
  filter = true,
  rule = false,
  look,
  follow = false,
  className,
}: {
  pose: VahtiPose
  size?: number
  label?: string
  filter?: boolean
  /** Peek only: draw the line it peeks over. */
  rule?: boolean
  /** Peek only: where the pupils point, in drawing units (default: down at the line). */
  look?: [number, number]
  /** Peek only: the pupils follow the pointer around the page. */
  follow?: boolean
  className?: string
}) {
  const svg = useRef<SVGSVGElement>(null)
  const shift = usePointerLook(svg, follow && pose === 'peek')
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const text = label ?? LABEL[pose]
  const a11y = text ? { role: 'img', 'aria-label': text } : { 'aria-hidden': true }
  const cls = `vahti vahti--${pose}${className ? ` ${className}` : ''}`
  const ink = filter ? `url(#ink-${id})` : undefined
  const defs = filter && (
    <filter id={`ink-${id}`} x="-5%" y="-5%" width="110%" height="110%">
      <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves={2} seed={7} result="n" />
      <feDisplacementMap in="SourceGraphic" in2="n" scale={2.6} xChannelSelector="R" yChannelSelector="G" />
    </filter>
  )

  if (pose === 'peek') {
    return (
      <svg ref={svg} className={cls} viewBox="22 4 76 74" width={size} height={(size * 74) / 76} {...a11y}>
        <defs>
          {defs}
          <clipPath id={`line-${id}`}>
            <rect x={0} y={-40} width={120} height={116} />
          </clipPath>
        </defs>
        <g clipPath={`url(#line-${id})`}>
          <g className="v-head" filter={ink}>
            <path d={TUFT_L} fill={INK} />
            <path d={TUFT_R} fill={INK} />
            <path d={PEEK_BODY} fill={INK} />
            <Eyes look={look ?? [0, 4]} shift={shift} />
          </g>
        </g>
        {rule && <path d="M22 76 H98" stroke={INK} strokeWidth={4} />}
      </svg>
    )
  }
  return (
    <svg className={cls} viewBox="0 0 120 140" width={size} height={(size * 140) / 120} {...a11y}>
      {defs && <defs>{defs}</defs>}
      <g filter={ink}>
        <Pose pose={pose} />
      </g>
    </svg>
  )
}

/** ADA's wordmark: Vahti peeking over the baseline, then "ada". */
export function AdaMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span className={`inline-flex items-end gap-1.5 leading-none ${className ?? ''}`} aria-label="ADA" role="img">
      <Vahti pose="peek" size={size} label="" filter={false} rule follow className="vahti--rise" />
      <span aria-hidden="true" className="font-bold tracking-tighter" style={{ fontSize: size * 0.82 }}>
        ada
      </span>
    </span>
  )
}
