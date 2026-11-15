import { useState, type KeyboardEvent } from 'react'

import { formatNumber } from '@/lib/columns'
import { usePaper, type Loaded } from '@/lib/runtime'

import { binLabel, buildMap, CLASSES, placeLabels, shortNames, type Label, type MapModel, type Region } from './model'

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
  const paper = usePaper()
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
  // Labels on paper only, where there is no tooltip; in the map's own units, so they scale
  // with it.
  const size = Math.max(model.box[2], model.box[3]) / 46
  const short = shortNames(drawn.map((r) => r.name))
  const texts = new Map(drawn.map((r, index) => [r.code, [short[index], ...(r.value === null ? [] : [formatNumber(r.value)])]]))
  // On paper a margin round the outlines, for labels and moved numbers at the edge.
  const margin = size * 2
  const view: MapModel['box'] = paper ? [model.box[0] - margin, model.box[1] - margin, model.box[2] + 2 * margin, model.box[3] + 2 * margin] : model.box
  const labels = paper ? placeLabels(drawn, texts, size, [view[0], view[1], view[0] + view[2], view[1] + view[3]]) : []
  const keyed = labels.filter((label): label is Extract<Label, { number: number }> => 'number' in label)
  const description = `Map of ${model.value} by region, ${drawn.length} regions${
    model.period ? `, ${model.period}` : ''
  }. Use the arrow keys to read each region.`

  return (
    <>
      <div className="ada-map">
        <svg
          viewBox={view.join(' ')}
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
              // The borders as attributes: a picture of the widget loses what a class gives.
              stroke="var(--surface)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              className={index === active ? 'ada-region ada-region-active' : 'ada-region'}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive((current) => (current === index ? null : current))}
            />
          ))}
          {/* Drawn last, so its outline is not hidden under a neighbour's. */}
          {region && <path d={region.path} className="ada-region-outline" aria-hidden="true" />}
          {/* Colours as attributes, not classes: a picture of the widget (a report's PDF)
              keeps attributes but loses what a class gives. */}
          {paper && (
          <g
            className="ada-map-labels"
            aria-hidden="true"
            fontSize={size}
            fontWeight={500}
            fill="var(--text-primary)"
            stroke="var(--surface)"
            strokeWidth={size / 6}
            strokeLinejoin="round"
            paintOrder="stroke"
          >
            {labels.map((label) =>
              'number' in label ? (
                <g key={label.code}>
                  {label.from && <line x1={label.from[0]} y1={label.from[1]} x2={label.x} y2={label.y} stroke="var(--text-secondary)" strokeWidth={size / 10} />}
                  <circle cx={label.x} cy={label.y} r={size * 0.62} fill="var(--surface)" stroke="var(--text-secondary)" strokeWidth={size / 10} />
                  <text x={label.x} y={label.y} dy="0.35em" textAnchor="middle" fontSize={size * 0.8} stroke="none">
                    {label.number}
                  </text>
                </g>
              ) : (
                <text key={label.code} x={label.x} y={label.y - ((label.lines.length - 1) * size * 1.15) / 2} textAnchor="middle">
                  {label.lines.map((line, index) => (
                    <tspan key={index} x={label.x} dy={index === 0 ? '0.35em' : '1.15em'} fontWeight={index ? 400 : undefined}>
                      {line}
                    </tspan>
                  ))}
                </text>
              ),
            )}
          </g>
          )}
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
      {keyed.length > 0 && (
        <ol className="ada-map-key" aria-hidden="true">
          {keyed.map((label) => (
            <li key={label.code}>
              <span className="ada-map-key-number">{label.number}</span> {(texts.get(label.code) ?? []).join(' ')}
            </li>
          ))}
        </ol>
      )}
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
