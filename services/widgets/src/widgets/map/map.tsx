import { useState, type KeyboardEvent } from 'react'

import { formatNumber } from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

import { binLabel, buildMap, CLASSES, type MapModel, type Region } from './model'

// Hand-written SVG, like the line chart: the outlines come with the data, so drawing them
// is one path per region, and a map library would add far more to every bundle than it
// saves here.

/** The fill of a region: a step of the sequential ramp, or the missing pattern. */
function fill(region: Region, bins: number): string {
  if (region.state === 'suppressed') return 'url(#ada-map-suppressed)'
  if (region.bin === null) return 'var(--map-missing)'
  // With one class (every value the same) take the middle of the ramp.
  const step = bins === 1 ? Math.ceil(CLASSES / 2) : region.bin + 1
  return `var(--seq-${step})`
}

function describe(region: Region): string {
  if (region.state === 'suppressed') return 'suppressed'
  if (region.value === null) return 'no data'
  const bounds =
    region.lower !== null && region.upper !== null
      ? ` (${formatNumber(region.lower)}–${formatNumber(region.upper)})`
      : ''
  return `${formatNumber(region.value)}${bounds}`
}

/**
 * A choropleth: each region coloured by the class of its value, from the operator's own
 * rows. The region code is the geography role's column, the outlines a GeoJSON column.
 *
 * Spec: `value` (default: the first measure role, else the first numeric column),
 * `geometry` (default: "geometry"), `label` (default: a column "name", else the code).
 * Each region shows its latest period; suppressed and missing values are drawn as missing,
 * never as a colour of the scale.
 */
export function RegionMap(loaded: Loaded) {
  const model = buildMap(loaded)
  if ('problem' in model) {
    return (
      <p role="alert" className="ada-error">
        {model.problem}
      </p>
    )
  }
  return <Choropleth model={model} title={loaded.widget.title} />
}

function Choropleth({ model, title }: { model: MapModel; title: string }) {
  const [active, setActive] = useState<number | null>(null)
  const drawn = model.regions.filter((region) => region.path)
  if (drawn.length === 0) return <p className="ada-note">No region outlines to draw.</p>

  const key = (event: KeyboardEvent) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (event.key === 'Escape') setActive(null)
    if (!step) return
    event.preventDefault()
    setActive((current) => {
      const next = (current ?? (step > 0 ? -1 : drawn.length)) + step
      return (next + drawn.length) % drawn.length
    })
  }
  const region = active === null ? null : drawn[active]
  const description = `Map of ${model.value} by region, ${drawn.length} regions${
    model.period ? `, ${model.period}` : ''
  }. Use the arrow keys to read each region.`

  return (
    <>
      <div className="ada-map">
        <svg
          viewBox={model.box.join(' ')}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={title ? `${title}: ${description}` : description}
          tabIndex={0}
          onKeyDown={key}
          onBlur={() => setActive(null)}
        >
          <defs>
            <pattern id="ada-map-suppressed" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="8" height="8" fill="var(--map-missing)" />
              <line x1="0" y1="0" x2="0" y2="8" stroke="var(--text-muted)" strokeWidth="2" />
            </pattern>
          </defs>
          {drawn.map((r, index) => (
            <path
              key={r.code}
              data-region={r.code}
              data-state={r.state}
              d={r.path}
              fill={fill(r, model.bins.length)}
              fillRule="evenodd"
              className={index === active ? 'ada-region ada-region-active' : 'ada-region'}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive((current) => (current === index ? null : current))}
            />
          ))}
          {/* Drawn last, so its outline is not hidden under a neighbour's. */}
          {region && <path d={region.path} className="ada-region-outline" aria-hidden="true" />}
        </svg>
        {region && (
          <div className="ada-tooltip ada-map-tooltip" role="status">
            <strong>{region.name}</strong>
            <div>
              {model.value}: {describe(region)}
            </div>
            {region.period && region.period !== model.period && <div className="ada-muted">{region.period}</div>}
          </div>
        )}
      </div>
      <Legend model={model} />
      {/* Hidden by its wrapper: a table keeps its full height whatever it is told. */}
      <div className="sr-only">
        <table>
          <caption>
            {model.value} by region{model.period ? `, ${model.period}` : ''}
          </caption>
          <thead>
            <tr>
              <th scope="col">Region</th>
              <th scope="col">{model.value}</th>
              <th scope="col">Period</th>
            </tr>
          </thead>
          <tbody>
            {model.regions.map((r) => (
              <tr key={r.code}>
                <th scope="row">{r.name}</th>
                <td>{describe(r)}</td>
                <td>{r.period ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Legend({ model }: { model: MapModel }) {
  return (
    <ul className="ada-legend" aria-label="Legend">
      {model.bins.map((bin, index) => (
        <li key={index}>
          <span
            className="ada-swatch ada-swatch-area"
            style={{ background: `var(--seq-${model.bins.length === 1 ? Math.ceil(CLASSES / 2) : index + 1})` }}
          />
          {binLabel(bin)}
        </li>
      ))}
      {model.hasMissing && (
        <li>
          <span className="ada-swatch ada-swatch-area ada-swatch-missing" />
          No data
        </li>
      )}
      {model.hasSuppressed && (
        <li>
          <span className="ada-swatch ada-swatch-area ada-swatch-suppressed" />
          Suppressed
        </li>
      )}
      {model.period && <li className="ada-muted">{model.period}</li>}
    </ul>
  )
}
