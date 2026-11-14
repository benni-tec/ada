import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { AgentSettings, DataSource, JudgeDefaults, JudgeKind, JudgeSettings, LlmProvider, Verdict } from '@/lib/api'

import { json, models, project, renderAt, serveApi, widget } from './app'

// The settings modal (docs/contracts.md, "Settings"): what all projects share (models and
// providers, agent instructions, the web) and this project's (data sources, its
// instructions), over whatever page is open.

function provider(overrides: Partial<LlmProvider> = {}): LlmProvider {
  return {
    id: 'pv1',
    name: 'gemini',
    kind: 'gemini',
    base_url: null,
    has_api_key: true,
    created_at: '2026-11-01T09:00:00Z',
    revision: 1,
    ...overrides,
  }
}

function settings(overrides: Partial<AgentSettings> = {}): AgentSettings {
  return {
    providers: [provider()],
    models: models(),
    session_agent: 'gemini/flash',
    secrets_available: true,
    instructions: '',
    revision: 3,
    ...overrides,
  }
}

function source(overrides: Partial<DataSource> = {}): DataSource {
  return {
    id: 'ds1',
    project_id: 'p1',
    name: 'Sotkanet screening',
    access_kind: 'url',
    address: 'https://sotkanet.test/screening.csv',
    format: 'csv',
    options: {},
    freshness: { kind: 'ttl', ttl_seconds: 86400, latest_period_ttl_seconds: null },
    declared_schema: null,
    created_at: '2026-11-01T09:00:00Z',
    last_checked_at: null,
    last_probe_token: null,
    last_error: null,
    revision: 1,
    ...overrides,
  }
}

/** The project's frame (sidebar, overview) and the settings, with the given overrides. */
function serveSettings(overrides: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [],
    'GET /api/projects/p1/dashboards': [],
    'GET /api/projects/p1/reports': [],
    'GET /api/projects/p1/alerts': [],
    'GET /api/projects/p1/sources': [source()],
    'GET /api/settings/agent': settings(),
    'GET /api/settings/web': { context_dev_configured: true, daily_credit_limit: 300 },
    ...overrides,
  })
}

const dialog = () => screen.findByRole('dialog', { name: 'Settings' })
const agents = () => screen.findByRole('region', { name: 'Models and providers' })
const dataSources = () => screen.findByRole('region', { name: 'Data sources' })
const navGroup = async (name: string) =>
  within(within(await dialog()).getByRole('navigation', { name: 'Settings sections' })).getByRole('group', { name })

test('the gear opens the settings over the page; the side navigation switches sections; Escape closes them', async () => {
  serveSettings()
  renderAt('/projects/p1')

  const gear = await screen.findByRole('link', { name: 'Settings' })
  expect(gear).toHaveAttribute('href', '/projects/p1?settings=models')
  fireEvent.click(gear)

  expect(await within(await dialog()).findByRole('region', { name: 'Models and providers' })).toBeInTheDocument()
  await waitFor(() => expect(gear).toHaveAttribute('data-active'))
  const global = await navGroup('Global')
  expect(global).toHaveTextContent('Shared by all projects')
  expect(within(global).getByRole('link', { name: 'Models and providers' })).toHaveAttribute('aria-current', 'page')
  expect(await navGroup('This project')).toHaveTextContent('Screening')

  fireEvent.click(within(global).getByRole('link', { name: 'Web' }))
  const web = await screen.findByRole('region', { name: 'Web' })
  expect(await within(web).findByText('Web credits per project per day')).toBeInTheDocument()
  expect(within(web).getByText('300')).toBeInTheDocument()
  // Context.dev has its key; Exa and watching (no ADA_PUBLIC_URL) have not.
  expect(within(web).getAllByText('Configured')).toHaveLength(1)
  expect(within(web).getByText('Web search')).toBeInTheDocument()
  expect(within(web).getAllByText('EXA_API_KEY').length).toBeGreaterThan(0)
  expect(within(web).getByText('ADA_PUBLIC_URL')).toBeInTheDocument()

  fireEvent.click(within(await navGroup('This project')).getByRole('link', { name: 'Data sources' }))
  expect(await within(await dataSources()).findByRole('listitem', { name: 'Sotkanet screening' })).toHaveAttribute(
    'id',
    'source-ds1',
  )

  // The overview is still beneath; Escape returns to it.
  fireEvent.keyDown(await dialog(), { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(gear).not.toHaveAttribute('data-active')
})

test('the old settings address opens the modal, at the data source it names', async () => {
  serveSettings()
  renderAt('/projects/p1/settings#source-ds1')

  const item = await within(await dataSources()).findByRole('listitem', { name: 'Sotkanet screening' })
  expect(item).toHaveAttribute('data-marked')
  expect(within(await navGroup('This project')).getByRole('link', { name: 'Data sources' })).toHaveAttribute(
    'aria-current',
    'page',
  )
})

test('the instructions for every project and for this project are saved with their revisions', async () => {
  const put: unknown[] = []
  const patched: unknown[] = []
  let current = settings()
  let currentProject = project()
  serveSettings({
    'GET /api/settings/agent': () => current,
    'PUT /api/settings/agent-instructions': (body: { instructions: string }) => {
      put.push(body)
      current = { ...current, instructions: body.instructions, revision: 4 }
      return current
    },
    'GET /api/projects/p1': () => currentProject,
    'PATCH /api/projects/p1': (body: { agent_instructions: string }) => {
      patched.push(body)
      currentProject = { ...currentProject, agent_instructions: body.agent_instructions, revision: 2 }
      return currentProject
    },
  })
  renderAt('/projects/p1?settings=agent-instructions')

  const everyProject = await screen.findByRole('form', { name: 'Instructions for every project' })
  fireEvent.change(within(everyProject).getByLabelText('Instructions for every project'), {
    target: { value: 'Use the Context.dev skill.' },
  })
  fireEvent.click(within(everyProject).getByRole('button', { name: 'Save' }))
  expect(await within(everyProject).findByRole('status')).toHaveTextContent('Saved')
  expect(put).toEqual([{ instructions: 'Use the Context.dev skill.', expected_revision: 3 }])

  fireEvent.click(within(await navGroup('This project')).getByRole('link', { name: 'Agent instructions' }))
  const thisProject = await screen.findByRole('form', { name: 'Instructions for this project' })
  fireEvent.change(within(thisProject).getByLabelText('Instructions for this project'), {
    target: { value: 'Answer in English.' },
  })
  fireEvent.click(within(thisProject).getByRole('button', { name: 'Save' }))
  expect(await within(thisProject).findByRole('status')).toHaveTextContent('Saved')
  expect(patched).toEqual([{ agent_instructions: 'Answer in English.', expected_revision: 1 }])
  expect(within(thisProject).getByLabelText('Instructions for this project')).toHaveValue('Answer in English.')
})

test('“Upload a PDF” posts the file, then registers a document source on its address', async () => {
  const uploads: { filename: string | null; content: string }[] = []
  const registered: unknown[] = []
  let sources = [source()]
  serveSettings({
    'GET /api/projects/p1/sources': () => sources,
    'POST /api/projects/p1/files': async (_body: unknown, request: Request) => {
      uploads.push({ filename: new URL(request.url).searchParams.get('filename'), content: await request.text() })
      return json({ address: 'upload://p1/abc.pdf', sha256: 'abc', size: 9 }, 201)
    },
    'POST /api/projects/p1/sources': (body: unknown) => {
      registered.push(body)
      const added = source({ id: 'ds2', name: 'Strategy', access_kind: 'document', format: 'pdf', address: 'upload://p1/abc.pdf' })
      sources = [...sources, added]
      return json(added, 201)
    },
  })
  renderAt('/projects/p1?settings=data-sources')

  const section = await dataSources()
  fireEvent.click(await within(section).findByRole('button', { name: 'Upload a PDF' }))
  const form = within(section).getByRole('form', { name: 'Upload a PDF' })
  const file = new File(['%PDF-1.7'], 'Strategy.pdf', { type: 'application/pdf' })
  fireEvent.change(within(form).getByLabelText('PDF file'), { target: { files: [file] } })
  expect(within(form).getByLabelText('Name')).toHaveValue('Strategy')
  fireEvent.change(within(form).getByLabelText('Engine'), { target: { value: 'context.dev' } })
  fireEvent.change(within(form).getByLabelText('Extract'), { target: { value: 'tables' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Upload and add' }))

  expect(await within(section).findByRole('listitem', { name: 'Strategy' })).toBeInTheDocument()
  expect(uploads).toEqual([{ filename: 'Strategy.pdf', content: '%PDF-1.7' }])
  expect(registered).toEqual([
    {
      name: 'Strategy',
      access_kind: 'document',
      format: 'pdf',
      address: 'upload://p1/abc.pdf',
      options: { engine: 'context.dev', extract: 'tables' },
    },
  ])
})

test('a provider added with a key shows “Key stored”, and the key is never shown again', async () => {
  const posted: unknown[] = []
  let current = settings({ providers: [], models: { models: [], session_agent: null }, session_agent: null })
  serveSettings({
    'GET /api/settings/agent': () => current,
    'GET /api/llm/models': () => current.models,
    'POST /api/settings/llm-providers': (body: unknown) => {
      posted.push(body)
      const added = provider({ id: 'pv2', name: 'mistral', kind: 'openai-compatible', base_url: 'https://api.mistral.test/v1' })
      current = { ...current, providers: [added] }
      return json(added, 201)
    },
  })
  renderAt('/projects/p1?settings=models')

  const section = await agents()
  fireEvent.click(await within(section).findByRole('button', { name: 'Add provider' }))
  const form = within(section).getByRole('form', { name: 'New provider' })
  fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'mistral' } })
  fireEvent.change(within(form).getByLabelText('Kind'), { target: { value: 'openai-compatible' } })
  fireEvent.change(within(form).getByLabelText('Base URL'), { target: { value: 'https://api.mistral.test/v1' } })
  const key = within(form).getByLabelText('API key')
  expect(key).toHaveAttribute('type', 'password')
  fireEvent.change(key, { target: { value: 'sk-very-secret' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Add provider' }))

  const card = await within(section).findByRole('listitem', { name: 'Provider mistral' })
  expect(posted).toEqual([
    { name: 'mistral', kind: 'openai-compatible', base_url: 'https://api.mistral.test/v1', api_key: 'sk-very-secret' },
  ])
  expect(within(card).getByText('Key stored')).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent('sk-very-secret')
  expect(screen.queryByDisplayValue('sk-very-secret')).not.toBeInTheDocument()

  // Editing starts with an empty key field: the stored key is kept unless a new one is typed.
  fireEvent.click(within(card).getByRole('button', { name: 'Edit mistral' }))
  expect(within(card).getByLabelText('API key')).toHaveValue('')
  expect(within(card).getByLabelText('API key')).toHaveAccessibleDescription('A key is stored. Leave this empty to keep it.')
})

test('picking the session agent saves it with the settings’ revision; unavailable models cannot be picked', async () => {
  const put: unknown[] = []
  let current = settings()
  serveSettings({
    'GET /api/settings/agent': () => current,
    'PUT /api/settings/session-agent': (body: { model_id: string }) => {
      put.push(body)
      current = { ...current, session_agent: body.model_id, models: { ...current.models, session_agent: body.model_id }, revision: 4 }
      return current
    },
  })
  renderAt('/projects/p1?settings=models')

  const picker = await within(await agents()).findByLabelText('Session agent')
  expect(picker).toHaveValue('gemini/flash')
  expect(within(picker).getByRole('option', { name: /mistral\/large \(unavailable: MISTRAL_API_KEY is not set\)/ })).toBeDisabled()

  fireEvent.change(picker, { target: { value: 'gemini/pro' } })
  await waitFor(() => expect(put).toEqual([{ model_id: 'gemini/pro', expected_revision: 3 }]))
  await waitFor(() => expect(picker).toHaveValue('gemini/pro'))
})

test('without ADA_SECRET_KEY the page says keys cannot be stored, and key fields are disabled', async () => {
  serveSettings({ 'GET /api/settings/agent': settings({ secrets_available: false }) })
  renderAt('/projects/p1?settings=models')

  const section = await agents()
  const note = await within(section).findByRole('note')
  expect(note).toHaveTextContent('ADA_SECRET_KEY is not set, so API keys cannot be stored')
  fireEvent.click(within(section).getByRole('button', { name: 'Add provider' }))
  expect(within(within(section).getByRole('form', { name: 'New provider' })).getByLabelText('API key')).toBeDisabled()
})

test('a data source changed by someone else meanwhile is read again, and saving again replaces it', async () => {
  const patched: { expected_revision: number; name: string }[] = []
  let current = source()
  serveSettings({
    'GET /api/projects/p1/sources': () => [current],
    'PATCH /api/sources/ds1': (body: { expected_revision: number; name: string }) => {
      patched.push(body)
      if (body.expected_revision !== current.revision)
        return json({ detail: 'Stale revision', expected_revision: body.expected_revision, revision: current.revision }, 409)
      current = { ...current, name: body.name, revision: current.revision + 1 }
      return current
    },
  })
  renderAt('/projects/p1?settings=data-sources')

  const item = await within(await dataSources()).findByRole('listitem', { name: 'Sotkanet screening' })
  // Someone else renames it after the page read it.
  current = { ...current, name: 'Sotkanet (renamed)', revision: 2 }
  fireEvent.click(within(item).getByRole('button', { name: 'Edit Sotkanet screening' }))
  const form = within(item).getByRole('form', { name: 'Edit Sotkanet screening' })
  expect(within(form).getByLabelText('Fresh for (minutes)')).toHaveValue(1440)
  fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Screening coverage' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Save' }))

  expect(await within(form).findByRole('alert')).toHaveTextContent('Someone else changed this source while you were editing')
  fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
  expect(await within(await dataSources()).findByRole('listitem', { name: 'Screening coverage' })).toBeInTheDocument()
  expect(patched.map((body) => [body.expected_revision, body.name])).toEqual([
    [1, 'Screening coverage'],
    [2, 'Screening coverage'],
  ])
})

test('a source shows where it came from, says when its licence is unknown, and can be watched and unwatched', async () => {
  let current = source({
    provenance: {
      publisher: 'THL',
      licence: 'unknown',
      landing_page: 'https://thl.test/cancer',
      found_by: { query: 'cancer survival Finland', scope: 'data' },
      extracted_by_model: true,
      note: 'The page names no licence',
    },
  })
  serveSettings({
    'GET /api/projects/p1/sources': () => [current],
    'POST /api/sources/ds1/watch': () => (current = { ...current, monitor_id: 'm1' }),
    'DELETE /api/sources/ds1/watch': () => (current = { ...current, monitor_id: null }),
  })
  renderAt('/projects/p1?settings=data-sources')

  const item = await within(await dataSources()).findByRole('listitem', { name: 'Sotkanet screening' })
  expect(item).toHaveTextContent('THL')
  expect(item).toHaveTextContent('Licence unknown')
  expect(item).toHaveTextContent('The page names no licence')
  expect(item).toHaveTextContent('Model-extracted')
  expect(within(item).getByRole('link', { name: 'Landing page' })).toHaveAttribute('href', 'https://thl.test/cancer')

  fireEvent.click(within(item).getByRole('button', { name: 'Watch Sotkanet screening' }))
  expect(await within(item).findByText('Watched')).toBeInTheDocument()
  fireEvent.click(within(item).getByRole('button', { name: 'Stop watching Sotkanet screening' }))
  await waitFor(() => expect(within(item).queryByText('Watched')).not.toBeInTheDocument())
})

test('picking the research agent saves it beside the session agent', async () => {
  const put: unknown[] = []
  let current = settings()
  serveSettings({
    'GET /api/settings/agent': () => current,
    'PUT /api/settings/research-agent': (body: { model_id: string }) => {
      put.push(body)
      current = { ...current, research_agent: body.model_id, revision: 4 }
      return current
    },
  })
  renderAt('/projects/p1?settings=models')

  const picker = await within(await agents()).findByLabelText('Research agent')
  expect(picker).toHaveValue('')
  fireEvent.change(picker, { target: { value: 'gemini/pro' } })
  await waitFor(() => expect(put).toEqual([{ model_id: 'gemini/pro', expected_revision: 3 }]))
})

// Judges

function defaults(kind: JudgeKind, overrides: Partial<JudgeDefaults> = {}): JudgeDefaults {
  return { kind, strictness: 'warn', model_id: null, instructions: '', revision: 1, ...overrides }
}

function effective(kind: JudgeKind, overrides: Partial<JudgeSettings> = {}): JudgeSettings {
  return {
    project_id: 'p1',
    kind,
    strictness: 'warn',
    model_id: 'gemini/pro',
    instructions: '',
    overridden: [],
    revision: 0,
    ...overrides,
  }
}

function verdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    kind: 'text_widget',
    outcome: 'fail',
    passed: false,
    blocking: false,
    findings: [
      { message: 'No input backs 13.2', excerpt: 'gap of 13.2', severity: 'error' },
      { message: 'Cannot tell', excerpt: 'more than before', severity: 'warning' },
    ],
    model: 'gemini/pro',
    reason: null,
    content_hash: 'sha256:1',
    checked_at: '2026-11-14T10:00:00Z',
    ...overrides,
  }
}

const card = async (name: string) => screen.findByRole('region', { name })

test('the global judges: one card per kind, saved with its revision; a conflict keeps what was typed', async () => {
  const put: unknown[] = []
  let text = defaults('text_widget', { model_id: 'gemini/pro' })
  let conflictOnce = true
  serveSettings({
    'GET /api/llm/models': models(),
    'GET /api/settings/judges': () => [text, defaults('widget_code')],
    'PUT /api/settings/judges/text_widget': (body: { expected_revision: number }) => {
      put.push(body)
      if (conflictOnce) {
        conflictOnce = false
        text = { ...text, revision: 2 }
        return json({ detail: 'Changed meanwhile', expected_revision: 1, revision: 2 }, 409)
      }
      text = { ...text, ...(body as Partial<JudgeDefaults>), revision: 3 }
      return text
    },
  })
  renderAt('/projects/p1?settings=judges')

  const section = await screen.findByRole('region', { name: 'Judges' })
  expect(within(await navGroup('Global')).getByRole('link', { name: 'Judges' })).toHaveAttribute('aria-current', 'page')
  const texts = await card('Text widgets')
  expect(await card('Custom widget code')).toBeInTheDocument()
  expect(within(texts).getByRole('radio', { name: /^Warn/ })).toBeChecked()
  expect(within(texts).getByRole('radio', { name: /^Block/ })).toHaveAccessibleName(/stops a report version/)
  await waitFor(() => expect(within(texts).getByLabelText('Model')).toHaveValue('gemini/pro'))
  // No project words in the global section.
  expect(within(section).queryByText('Global default')).not.toBeInTheDocument()

  fireEvent.click(within(texts).getByRole('radio', { name: /^Block/ }))
  fireEvent.change(within(texts).getByLabelText('Model'), { target: { value: 'gemini/flash' } })
  fireEvent.change(within(texts).getByLabelText('Instructions'), { target: { value: 'Years are not figures.' } })
  fireEvent.click(within(texts).getByRole('button', { name: 'Save' }))

  // Someone saved first: read again, the typed values stay; saving again wins.
  expect(await within(texts).findByRole('alert')).toHaveTextContent('Someone else changed this judge')
  expect(within(texts).getByLabelText('Instructions')).toHaveValue('Years are not figures.')
  fireEvent.click(within(texts).getByRole('button', { name: 'Save' }))
  expect(await within(texts).findByRole('status')).toHaveTextContent('Saved')
  const change = { strictness: 'block', model_id: 'gemini/flash', instructions: 'Years are not figures.' }
  expect(put).toEqual([
    { ...change, expected_revision: 1 },
    { ...change, expected_revision: 2 },
  ])
})

test('without models, the judge’s model picker links to the models', async () => {
  serveSettings({
    'GET /api/llm/models': models({ models: [], session_agent: null }),
    'GET /api/settings/judges': [defaults('text_widget'), defaults('widget_code')],
  })
  const { router } = renderAt('/projects/p1?settings=judges')

  const link = await within(await card('Text widgets')).findByRole('link', { name: /Add one in Global › Models/ })
  fireEvent.click(link)
  await waitFor(() => expect(router.state.location.search).toEqual({ settings: 'models' }))
})

test('a project’s judges: each field inherits or is overridden, goes back to the default, and lists the verdicts', async () => {
  const put: unknown[] = []
  let text = effective('text_widget', {
    strictness: 'block',
    instructions: 'Years are not figures.\n\nThe target is 70 %.',
    overridden: ['strictness', 'instructions'],
    revision: 2,
  })
  serveSettings({
    'GET /api/llm/models': models(),
    'GET /api/settings/judges': [
      defaults('text_widget', { model_id: 'gemini/pro', instructions: 'Years are not figures.' }),
      defaults('widget_code'),
    ],
    'GET /api/projects/p1/judges': () => [text, effective('widget_code')],
    'PUT /api/projects/p1/judges/text_widget': (body: Record<string, unknown>) => {
      put.push(body)
      const overridden = new Set(text.overridden)
      for (const [field, value] of Object.entries(body)) {
        if (field === 'expected_revision') continue
        if (value === null) overridden.delete(field)
        else overridden.add(field)
      }
      text = {
        ...text,
        strictness: body.strictness === null ? 'warn' : ((body.strictness as JudgeSettings['strictness']) ?? text.strictness),
        model_id: (body.model_id as string | undefined) ?? text.model_id,
        overridden: [...overridden],
        revision: text.revision + 1,
      }
      return text
    },
    'GET /api/projects/p1/verdicts': (_: unknown, request: Request) =>
      new URL(request.url).searchParams.get('kind') === 'text_widget'
        ? [widget({ id: 'w7', type: 'text', title: 'Why the gap', verdict: verdict() })]
        : [],
  })
  renderAt('/projects/p1?settings=project-judges')

  const texts = await card('Text widgets')
  // The model follows the global default; strictness and instructions are set here.
  const model = within(texts).getByLabelText('Model')
  await waitFor(() => expect(model).toHaveValue('gemini/pro'))
  expect(model.parentElement!.parentElement).toHaveTextContent('Global default')
  expect(within(texts).getByRole('radio', { name: /^Block/ })).toBeChecked()
  expect(within(texts).getByText('Years are not figures.', { selector: 'p' })).toBeInTheDocument()
  expect(within(texts).getByLabelText('Instructions for this project')).toHaveValue('The target is 70 %.')
  expect(within(texts).getByText(/after the global instructions/)).toBeInTheDocument()

  // Its verdicts: the widget, the outcome with its count, when.
  const verdicts = within(texts).getByRole('list', { name: 'Recent verdicts' })
  const item = within(await within(texts).findByRole('link', { name: 'Why the gap' })).getByText('Why the gap').closest('li')!
  expect(within(verdicts).getByRole('link', { name: 'Why the gap' })).toHaveAttribute('href', '/projects/p1/widgets/w7')
  expect(item).toHaveTextContent('Failed: 2 findings')
  expect(within(item).getByRole('time')).toHaveAttribute('dateTime', '2026-11-14T10:00:00Z')
  expect(within(await card('Custom widget code')).getByText('No widget has been reviewed yet.')).toBeInTheDocument()

  // Overriding the model sends that field only.
  fireEvent.change(model, { target: { value: 'gemini/flash' } })
  fireEvent.click(within(texts).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(put).toEqual([{ model_id: 'gemini/flash', expected_revision: 2 }]))
  expect(await within(texts).findByRole('button', { name: 'Use global default for the model' })).toBeInTheDocument()

  // Back to the default: null.
  fireEvent.click(within(texts).getByRole('button', { name: 'Use global default for the strictness' }))
  await waitFor(() => expect(put).toHaveLength(2))
  expect(put[1]).toEqual({ strictness: null, expected_revision: 3 })
  await waitFor(() => expect(within(texts).getByRole('radio', { name: /^Warn/ })).toBeChecked())
  expect(within(texts).queryByRole('button', { name: 'Use global default for the strictness' })).not.toBeInTheDocument()
})
