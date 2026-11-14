import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { AgentSettings, DataSource, LlmProvider } from '@/lib/api'

import { json, models, project, renderAt, serveApi } from './app'

// The settings page (docs/contracts/settings.md): the agent shared by all projects, and
// the project's data sources.

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
    ...overrides,
  })
}

const agents = () => screen.findByRole('region', { name: 'Agents' })
const dataSources = () => screen.findByRole('region', { name: 'Data sources' })

test('the gear at the bottom of the sidebar opens the settings', async () => {
  serveSettings()
  renderAt('/projects/p1')

  const link = await screen.findByRole('link', { name: 'Settings' })
  expect(link).toHaveAttribute('href', '/projects/p1/settings')
  fireEvent.click(link)

  expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
  expect(document.querySelector('[data-page-type="settings"]')).toHaveTextContent('Settings')
  await waitFor(() => expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('data-active'))
  expect(within(await agents()).getByText(/Shared by all projects/)).toBeInTheDocument()
  expect(await within(await dataSources()).findByRole('listitem', { name: 'Sotkanet screening' })).toHaveAttribute(
    'id',
    'source-ds1',
  )
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
  renderAt('/projects/p1/settings')

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
  renderAt('/projects/p1/settings')

  const picker = await within(await agents()).findByLabelText('Session agent')
  expect(picker).toHaveValue('gemini/flash')
  expect(within(picker).getByRole('option', { name: /mistral\/large \(unavailable: MISTRAL_API_KEY is not set\)/ })).toBeDisabled()

  fireEvent.change(picker, { target: { value: 'gemini/pro' } })
  await waitFor(() => expect(put).toEqual([{ model_id: 'gemini/pro', expected_revision: 3 }]))
  await waitFor(() => expect(picker).toHaveValue('gemini/pro'))
})

test('without ADA_SECRET_KEY the page says keys cannot be stored, and key fields are disabled', async () => {
  serveSettings({ 'GET /api/settings/agent': settings({ secrets_available: false }) })
  renderAt('/projects/p1/settings')

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
  renderAt('/projects/p1/settings')

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
