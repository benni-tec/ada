import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { WidgetRuntime } from '@/lib/runtime'
import { coverage, loaded, widget } from '@/test/samples'
import { Any } from '@/widgets/any/any'

import { startChild } from './child'
import { Custom } from './custom'

// jsdom runs no module from a blob: URL, and no script in a frame's srcdoc. So the code's
// frame runs here, wired to the widget's frame by postMessage as the browser would.

/** Runs the sandboxed frame's script for the frame the widget made, drawing into `root`. */
async function runCodeFrame() {
  const frame = (await waitFor(() => {
    const element = document.querySelector<HTMLIFrameElement>('iframe.ada-custom')
    if (!element?.contentWindow) throw new Error('no frame yet')
    return element
  })) as HTMLIFrameElement
  const child = frame.contentWindow!
  const root = document.createElement('div')
  root.dataset.testid = 'drawn'
  document.body.append(root)
  startChild({
    send: (data) => window.dispatchEvent(new MessageEvent('message', { data, source: child })),
    listen: (handler) => child.addEventListener('message', (event) => handler((event as MessageEvent).data)),
    errors: new EventTarget(),
    root,
    // The module's default export, as importing it from a blob: URL gives it.
    load: async (code) => ({ default: new Function(`return (${code.replace('export default', '')})`)() }),
    libraries: {},
  })
  return { frame, root }
}

const bars = `export default function render(root, data, ada) {
  const targets = data.inputs.targets.rows
  root.textContent = data.main.rows.map((row, i) =>
    row.region + ': ' + ada.format.number(row.coverage, { format: 'percent', decimals: 1 }) + ' of ' + targets[i].target
  ).join(', ') + ' (' + ada.theme + ')'
}`

test('reads every input in one run, draws the code, and clears the error ADA had', async () => {
  const custom = widget({
    type: 'custom',
    title: 'Coverage against targets',
    spec: { code: bars, libraries: ['d3'] },
    inputs: { targets: 'op_2' },
    render_error: 'targets is not defined',
  })
  const main = coverage({
    columns: [
      { name: 'region', type: 'text' },
      { name: 'coverage', type: 'number' },
    ],
    rows: [
      ['North', 64.25],
      ['South', 72.5],
    ],
  })
  const targets = coverage({ input: 'targets', columns: [{ name: 'target', type: 'integer' }], rows: [[70], [75]] })
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const answer = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
    if (url === '/api/widgets/w1') return answer(custom)
    if (url === '/api/widgets/w1/data?limit=1000&run_id=r9') return answer(main)
    if (url === '/api/widgets/w1/data?limit=5000&run_id=r1&input=targets') return answer(targets)
    if (url === '/api/widgets/w1/render' && init?.method === 'POST') return new Response(null, { status: 204 })
    return new Response(JSON.stringify({ detail: `unexpected ${url}` }), { status: 500 })
  })
  vi.stubGlobal('fetch', fetch)
  window.location.hash = '#widget=w1&run=r9'
  render(<WidgetRuntime>{(loaded) => <Any {...loaded} />}</WidgetRuntime>)

  const { frame, root } = await runCodeFrame()
  // Sandboxed without ADA's origin, no network, and only the listed library.
  expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
  expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'; script-src 'unsafe-inline' blob:")
  await waitFor(() => expect(root).toHaveTextContent('North: 64.3 % of 70, South: 72.5 % of 75 (light)'))
  // It drew: the error ADA had is cleared, once.
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith('/api/widgets/w1/render', expect.objectContaining({ body: '{"error":null}' })),
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('shows what the code threw, and reports it to ADA', async () => {
  const fetch = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetch)
  const thrower = 'export default function render() { throw new Error(\'no column "cases"\') }'
  render(<Custom {...loaded({ widget: widget({ type: 'custom', spec: { code: thrower } }) })} />)
  await runCodeFrame()

  expect(await screen.findByRole('alert')).toHaveTextContent('This widget could not be drawn: no column "cases"')
  expect(fetch).toHaveBeenCalledWith(
    '/api/widgets/w1/render',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ error: 'no column "cases"' }) }),
  )
})
