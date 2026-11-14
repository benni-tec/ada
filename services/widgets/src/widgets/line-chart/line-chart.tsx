import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import { formatNumber, formatTick } from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

import { allYearStarts, buildChart, niceTicks, runs, xLabel, type ChartModel, type Point } from './model'

// Hand-written SVG instead of a chart library: the bundle is inlined into one HTML file
// per widget, and bands and gaps are a few path commands, so a library would add size
// without saving code.

const MARGIN = { top: 8, right: 16, bottom: 24, left: 44 }
// jsdom and the first paint have no layout yet; draw at a reasonable size until measured.
const FALLBACK_SIZE = { width: 480, height: 240 }

function color(index: number) {
  return `var(--series-${index + 1})`
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState(FALLBACK_SIZE)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, size] as const
}

/**
 * Lines over x, one per value of the series column.
 *
 * Spec: `x` (default: the time role's start, else the first date column), `y` (default:
 * the first measure role, else the first numeric column), `series` (a column to split
 * by). A confidence band is drawn when the y measure declares lower and upper bounds;
 * suppressed and missing values leave gaps.
 */
export function LineChart(loaded: Loaded) {
  const model = buildChart(loaded)
  if ('problem' in model) {
    return (
      <p role="alert" className="ada-error">
        {model.problem}
      </p>
    )
  }
  return <Chart model={model} title={loaded.widget.title} />
}

function Chart({ model, title }: { model: ChartModel; title: string }) {
  const [ref, { width, height }] = useSize<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)

  const points = model.series.flatMap((series) => series.points)
  const xs = [...new Set(points.map((point) => point.x))].sort((a, b) => a - b)
  const values = points.flatMap((point) =>
    point.y === null ? [] : [point.y, point.lower ?? point.y, point.upper ?? point.y],
  )
  if (xs.length === 0 || values.length === 0) {
    return <p className="ada-note">No values to draw.</p>
  }

  const yearsOnly = model.xKind === 'time' && allYearStarts(xs)
  const yTicks = niceTicks(Math.min(...values), Math.max(...values))
  const [yMin, yMax] = [yTicks[0], yTicks[yTicks.length - 1]]
  const [xMin, xMax] = [xs[0], xs[xs.length - 1]]
  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 1)
  const innerHeight = Math.max(height - MARGIN.top - MARGIN.bottom, 1)
  const sx = (x: number) => MARGIN.left + (xMax === xMin ? innerWidth / 2 : ((x - xMin) / (xMax - xMin)) * innerWidth)
  const sy = (y: number) => MARGIN.top + innerHeight - ((y - yMin) / (yMax - yMin)) * innerHeight

  // Labels need about 64px each; pick evenly spaced data positions that fit.
  const maxXTicks = Math.max(2, Math.floor(innerWidth / 64))
  const stride = Math.ceil(xs.length / maxXTicks)
  const xTicks = xs.filter((_, i) => i % stride === 0)

  const line = (run: Point[]) => run.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x)},${sy(p.y!)}`).join('')
  const band = (run: Point[]) =>
    `${run.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x)},${sy(p.upper!)}`).join('')}` +
    `${[...run].reverse().map((p) => `L${sx(p.x)},${sy(p.lower!)}`).join('')}Z`

  const activeX = active === null ? null : xs[active]
  const move = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const offset = event.clientX - box.left + MARGIN.left
    let nearest = 0
    xs.forEach((x, i) => {
      if (Math.abs(sx(x) - offset) < Math.abs(sx(xs[nearest]) - offset)) nearest = i
    })
    setActive(nearest)
  }
  const key = (event: KeyboardEvent) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    event.preventDefault()
    setActive((current) => Math.min(Math.max((current ?? (step > 0 ? -1 : xs.length)) + step, 0), xs.length - 1))
  }

  const description = `Line chart of ${model.y} by ${model.x}${
    model.series.length > 1 ? `, ${model.series.length} series` : ''
  }, from ${xLabel(model, xMin, yearsOnly)} to ${xLabel(model, xMax, yearsOnly)}`

  return (
    <>
      <div className="ada-chart" ref={ref}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={title ? `${title}: ${description}` : description}
          tabIndex={0}
          onKeyDown={key}
          onBlur={() => setActive(null)}
        >
          <g className="ada-axis" aria-hidden="true">
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={sy(tick)} y2={sy(tick)} />
                <text x={MARGIN.left - 6} y={sy(tick)} textAnchor="end" dominantBaseline="middle">
                  {formatTick(tick)}
                </text>
              </g>
            ))}
            {xTicks.map((tick) => (
              <text key={tick} x={sx(tick)} y={height - 6} textAnchor="middle">
                {xLabel(model, tick, yearsOnly)}
              </text>
            ))}
          </g>
          {model.series.map((series, i) => (
            <g key={series.key} data-series={series.key}>
              {runs(series.points, (p) => p.y !== null && p.lower !== null && p.upper !== null).map((run) => (
                <path
                  key={`band-${run[0].x}`}
                  className="ada-band"
                  d={band(run)}
                  fill={color(i)}
                  fillOpacity={0.12}
                  stroke="none"
                />
              ))}
              {runs(series.points).map((run) =>
                run.length === 1 ? (
                  // A value between two gaps has no line to sit on; mark it with a dot.
                  <circle key={`dot-${run[0].x}`} cx={sx(run[0].x)} cy={sy(run[0].y!)} r={3} fill={color(i)} />
                ) : (
                  <path
                    key={`line-${run[0].x}`}
                    className="ada-line"
                    d={line(run)}
                    fill="none"
                    stroke={color(i)}
                    strokeWidth={2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                ),
              )}
            </g>
          ))}
          {activeX !== null && (
            <g aria-hidden="true">
              <line
                x1={sx(activeX)}
                x2={sx(activeX)}
                y1={MARGIN.top}
                y2={MARGIN.top + innerHeight}
                stroke="var(--text-muted)"
                strokeWidth={1}
              />
              {model.series.map((series, i) => {
                const point = series.points.find((p) => p.x === activeX)
                return point && point.y !== null ? (
                  <circle
                    key={series.key}
                    cx={sx(activeX)}
                    cy={sy(point.y)}
                    r={4}
                    fill={color(i)}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ) : null
              })}
            </g>
          )}
          {/* Larger than the marks, so the pointer finds the nearest x anywhere in the plot. */}
          <rect
            x={MARGIN.left}
            y={MARGIN.top}
            width={innerWidth}
            height={innerHeight}
            fill="transparent"
            onPointerMove={move}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
        {activeX !== null && (
          <Tooltip model={model} x={activeX} left={sx(activeX)} width={width} yearsOnly={yearsOnly} />
        )}
      </div>
      <Legend model={model} />
    </>
  )
}

function Tooltip({
  model,
  x,
  left,
  width,
  yearsOnly,
}: {
  model: ChartModel
  x: number
  left: number
  width: number
  yearsOnly: boolean
}) {
  // Flip to the left of the crosshair in the right half, so it stays inside the frame.
  const style = left > width / 2 ? { right: width - left + 8, top: MARGIN.top } : { left: left + 8, top: MARGIN.top }
  return (
    <div className="ada-tooltip" style={style} role="status">
      <strong>{xLabel(model, x, yearsOnly)}</strong>
      <dl>
        {model.series.map((series, i) => {
          const point = series.points.find((p) => p.x === x)
          const text = !point
            ? '–'
            : point.suppressed
              ? 'suppressed'
              : point.y === null
                ? '–'
                : point.lower !== null && point.upper !== null
                  ? `${formatNumber(point.y)} (${formatNumber(point.lower)}–${formatNumber(point.upper)})`
                  : formatNumber(point.y)
          return (
            <div key={series.key} style={{ display: 'contents' }}>
              <dt style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="ada-swatch" style={{ background: color(i) }} />
                {series.key}
              </dt>
              <dd>{text}</dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}

function Legend({ model }: { model: ChartModel }) {
  const notes = [
    model.hasBand && 'Shaded: confidence interval',
    model.hasSuppressed && 'Gaps: suppressed values',
    model.hiddenSeries > 0 && `${model.hiddenSeries} more series not shown`,
  ].filter((note): note is string => Boolean(note))
  if (model.series.length < 2 && notes.length === 0) return null
  return (
    <ul className="ada-legend" aria-label="Legend">
      {model.series.length > 1 &&
        model.series.map((series, i) => (
          <li key={series.key}>
            <span className="ada-swatch" style={{ background: color(i) }} />
            {series.key}
          </li>
        ))}
      {notes.map((note) => (
        <li key={note} className="ada-muted">
          {note}
        </li>
      ))}
    </ul>
  )
}
