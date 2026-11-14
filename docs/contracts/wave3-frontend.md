# Wave 3, frontend: what was built and decided

The frontend half of `docs/contracts/wave3.md`, for integration to fold into
`docs/contracts.md` (sections "Widgets" and "Frontend routes"). Everything the backend
builds in this wave is used through hand-written types (below) and tested against mocked
responses; nothing here needs a backend change beyond the wave 3 contract.

## shadcn/ui

- Installed with the shadcn CLI (4.23): style `radix-nova` (Radix primitives), Tailwind 4,
  neutral, lucide icons (`components.json`). Components in `src/components/ui/` exactly as
  the CLI wrote them: badge, bubble, button, code-block, collapsible, command, dialog,
  dropdown-menu, input, input-group, kbd, message, popover, scroll-area, separator,
  sheet, sidebar, skeleton, textarea, tooltip, **trace**. Only `hooks/use-mobile.ts` was
  rewritten (useSyncExternalStore instead of state set in an effect, which lint flags);
  the code-block's syntax highlighter (and with it `shiki`) was left out.
- **Theme.** shadcn switches colours on a `.dark` class, so `lib/theme.tsx` sets it from
  the person's choice (light, dark, or as the system, remembered in `localStorage`
  `ada-theme`), with a script in `index.html` so a dark page does not flash light. The
  theme menu is the sun or moon at the top right.
- **Widget frames follow the theme.** Inside a frame `prefers-color-scheme` follows the
  system, not the page. A theme picked apart from the system's goes into the frame's
  fragment, `#widget=…&run=…&theme=light|dark`; `services/widgets` (`host.ts`,
  `followTheme`, and `styles.css`) applies it and follows hash changes, so switching needs
  no reload. Without the parameter, page and widget both follow the system.
- **Tooltip** (`components/icon-action.tsx`): `Hint` puts shadcn's Tooltip on any control;
  `IconButton` is an icon-only button whose tooltip is also its `aria-label`, disabled
  with `aria-disabled` plus a reason (`unavailable`) so the keyboard still reaches it.
  Every icon-only control in the app has a name and a tooltip.
- **Dialog** (`components/modal.tsx`): shadcn's Dialog with an × (tooltip "Close"). It
  keeps what the hand-made one guaranteed: focus moves in (to `[data-autofocus]`, else the
  dialog itself, so no tooltip opens by itself and the first Escape closes the dialog),
  stays inside, and returns to the opener (Radix only does that for a DialogTrigger);
  Escape and a click outside close; the page behind is `inert` as well as `aria-hidden`.

## Layout

- **Sidebar** (`components/project-sidebar.tsx`, shadcn Sidebar): "All projects", the
  project (link to its overview), then the groups Sessions (+ new session dialog),
  Dashboards (+ new dashboard dialog), Reports (+ links to `/reports/new`), Alerts ("Feed
  and rules" with the firing count) and Data sources (each links to its card on the
  overview, `#source-<id>`, marked when its last refresh failed). The current item is
  marked (`data-active`, and the router's `aria-current="page"`). Sessions and reports
  newest first. Collapsible (the top bar's toggle, Ctrl/Cmd+B); a sheet on phones.
- **Pages** fill the width under a top bar with the sidebar toggle, the live indicator
  and the theme menu; each page scrolls inside (the session page has its own scroll areas).
- **Type labels.** No breadcrumbs (`components/breadcrumbs.tsx` is gone, and so is the
  route `crumb` static data). Every page shows its type with the sidebar's icon above its
  title (`PageType`, `PageHeader` in `components/page-header.tsx`; icons and labels in
  `lib/page-types.ts`).
- **Rename** is a pencil with the tooltip "Rename"; Enter saves, Escape cancels (without
  closing a dialog around it), the check and × save and cancel by pointer. Conflict
  handling is unchanged.
- **Project overview** (`/projects/{id}`): counts per kind, the five newest sessions with
  the dashboard beside them, and the data sources with their state. The lists of
  dashboards, reports, widgets and alerts moved to the sidebar (their old section
  components are deleted); widgets are no longer listed on their own.
- Icons instead of words where clear: dialog close, rename, version view and restore,
  alert rule check and edit, pin, open full size, go to session, detach, stop, send.
  Primary actions keep a word and an icon ("Add widget", "Generate report", "Edit layout").

## Widget cards

- Footer: **"Pipeline" with an open-in-a-popup icon** as one button that opens the
  pipeline dialog; the lineage is read only when it opens (the summary line and
  `labels.summary` are gone). At the right: "Open full size" (unless already full size),
  then "Add to dashboard" or, on a dashboard, "Go to the session it came from".
- The type is a badge in the header; the title is plain text.

## Widgets full size

- `?open=<widget id>` on any page of a project (validated on the project layout route)
  shows the widget in a modal over the page (`components/widget-modal.tsx`). The card's
  "Open full size" link (`open-widget-link.tsx`) pushes the address and puts the card's
  run in the history entry's state (`openRun`), so the modal shows the same numbers;
  closing (Escape, ×) goes back in history, as does the browser's back, and the page
  beneath was never unmounted, so its scroll position is kept. A direct link to `?open=`
  has no run in its state: the modal starts a run of its own, like the widget page, and
  closing replaces the address without `open`.
- In-app links no longer lead to `/projects/{id}/widgets/{id}`; a report's widget opens
  full size at the version's run. The widget page stays for direct links (MCP tools).

## Chat in sessions

- **Record** (`components/session-record.tsx`): the person's messages as bubbles on the
  right with their context chips (named from what they point at), other actors' on the
  left, agent turns (`agent_turn` entries, `ref` = turn id) as the agent's answers, and
  operators and widget cards as before.
- **Agent turn** (`components/chat/agent-turn.tsx`): read with `GET /turns/{id}`;
  consecutive non-text parts form one shadcn **Trace**: reasoning ("Thinking" open while
  it streams, "Thought" folded after), tool calls ("Calling / Called / Failed: <tool>",
  opening to their input and output or error as JSON), neighbouring sources as one line
  ("Used n sources", each a link when it has a URL). Text parts are the answer between
  them. Queued, running without parts, failed (with the error, `role="alert"`) and
  cancelled are said.
- **Streaming** (`lib/agent-turns.ts`, `lib/events.ts`, `lib/live.ts`): `agent.turn_part`
  puts the part at its index into the cached turn (a part replaces the one at its index).
  Parts of running turns are also kept aside, and a fetched turn gets those with a higher
  index than it has, so a refetch that lags behind the stream does not drop them.
  `agent.turn_started` and `agent.turn_finished` refetch the record and the turn; a
  finished turn's kept parts are forgotten. A reconnect forgets all kept parts and
  refetches everything, so every turn is read again and continues from there.
- **Composer** (`components/chat/composer.tsx`): Enter sends, Shift+Enter is a new line
  (Enter ending an IME composition is not a send); the body is `{text, context, model?}`
  with the chips' contexts flattened. Chips are removable. A model picker (DropdownMenu)
  lists `GET /api/llm/models`, default `session_agent`, unavailable models disabled with
  their reason; `model` is sent when the models are known. While the latest turn is
  queued or running a stop button posts `POST /turns/{id}/cancel`. Without an agent
  (`session_agent` null or not available, or a post answered with `turn: null`) the
  message is still recorded and a note says nobody will answer and how to configure
  `session_agent` in `llms.yml`. If the models route fails, the picker and the note are
  left out (the message is still sent, without `model`).
- **Add widget** (`components/chat/add-widget.tsx`): a Popover with shadcn Command over
  `GET /projects/{id}/pipelines`, searchable by name, source names and column names.
  Choosing one adds a chip. One chip may carry several contexts (`components/chat/
  chat-draft.ts`): on a dashboard, the pipeline and `{kind: "dashboard", dashboard_id,
  slot?}` together, removed together; no slot means a new one. The draft lives on the
  page, so "Add widget" elsewhere on the page can fill the composer, which then takes the
  focus.
- The record follows the bottom while the person is there (new entries, streaming text)
  and stays put when they scrolled up; `?widget=` still scrolls to and marks a widget.

## Session with a dashboard beside it

- Split half and half (`lg` and up; stacked below): the conversation, and the dashboard
  under a black bar (`bg-black`, both themes) saying "DASHBOARD" and its name (a link to
  it), with an × "Detach the dashboard" that sends `PATCH /sessions/{id}
  {panel_dashboard_id: null, expected_revision}`; the conversation then takes the full
  width. The half shows the dashboard's real grid (read only), which turns into one
  column by a container query when the half is narrow. Its empty slots offer "Add widget"
  into the session's composer, with the dashboard and slot.

## Dashboards

- **Agent panel** (`components/dashboards/agent-panel.tsx`): docked at the right, closed
  at first (opening it finds or creates the agent session, which a mere look should not
  do), remembered per browser (`localStorage` `ada-dashboard-agent-panel`). Opening calls
  `POST /dashboards/{id}/agent-session` once per page (`dashboardSessionQuery`, not under
  `['dashboards', id]` so dashboard events do not post again) and shows that session's
  chat; a link opens it as a session. "Add widget" in the header (new slot) and in empty
  slots (that slot) adds the chip and opens the panel.
- **Layout editing** (`components/dashboards/dashboard-grid.tsx`, `layout.ts`): "Edit
  layout" shows two handles per slot, on its corners: move and resize. Rows are 80 px,
  the gap 16 px, a widget fills its cell (`WidgetCard fill`). Dragging previews the
  layout; others in the way move down (never up or sideways). Maps keep their aspect
  ratio (the pixel ratio when the resize began; the width decides, or the height when
  only it changed); minimums: value 2×2, table, line chart and map 3×3, empty 2×2.
  Escape during a drag puts it back. A drop saves the full slot list with
  `PUT /dashboards/{id}/slots` and `expected_revision` (a new version); the grid shows the
  new layout until answered; a 409 reads the dashboard again and says so. Keyboard: Enter
  or Space on a handle picks the slot up, the arrows move or resize by one cell, Enter or
  Space drops (saves), Escape or leaving the handle puts it back; a live region says what
  happens. Handles exist only in the 12-column layout (container at least 48rem) and not
  on an old version.
- **Copies on pin**: the pin form says the dashboard gets a copy, and the project's
  widgets are refetched after a pin. "Go to the session it came from" uses the widget's
  `session_id`, else its original's (`copied_from`, read with `GET /widgets/{id}`), and
  links to `?widget=<that widget's id>`; disabled with "Not made in a session" when
  neither has one.

## Temporary types (integration replaces them)

- `src/lib/api/agent.ts`: `Context`, `TurnStatus`, the four `Part`s, `AgentTurn` (parts
  sparse while streaming), `LlmModel(s)`, `Pipeline`, `PostedMessage`, and the calls
  (`postMessage`, `getTurn`, `cancelTurn`, `listModels`, `listPipelines`,
  `openDashboardAgentSession`) on plain `fetch`, plus their query options.
- `src/lib/api/models.ts`: `EntryKind` gains `agent_turn`, `SessionEntry` gains
  `context`, `Widget` gains `copied_from`, `EventType` gains the three `agent.*` events;
  `listEntries` is typed with the extended entry.
- The old `addMessage` (`{text}` answered with an entry) is removed; messages go through
  `postMessage`.

**Integration must:** regenerate `openapi.json` and `schema.d.ts`
(`moon run frontend:generate`), replace `agent.ts`'s types with `Schemas[...]` names and
its calls with the typed client, drop the temporary additions in `models.ts` and the
`listEntries` annotation, and check that the generated `Part` uses the snake_case names
of the contract (`tool_call_id`, `tool_name`, `error_text`, `source_id`).

## Development mock

`src/dev/mock-agent.ts`, loaded only in a dev build and only with `?mock-agent=1` (until
`?mock-agent=0`, kept in `sessionStorage`): answers the wave 3 routes from memory (models,
pipelines derived from the project's widgets, messages and turns, dashboard agent
sessions) and streams a scripted turn as live events on the page's own stream. Nothing it
answers is written to the backend; every other request goes through. A production build
does not contain it.

## Tests

Vitest with mocked fetch and EventSource: `test/layout.test.tsx` (sidebar, current item,
type labels, new session, rename pencil, theme), `test/chat.test.tsx` (conversation, each
part type in Trace, sending with chips and model, Enter and Shift+Enter, removing a chip,
no agent, streaming by index with replacement, a part during a refetch, reconnect and
refetch, stop, failed turn, recorded context), `test/dashboard-editing.test.tsx` (drag,
map aspect and free resize, save on drop, 409, keyboard, handles only when editing, the
session link via `copied_from`, the agent panel, "Add widget" in the header and slots,
the widget modal with `?open=`, Escape and back, direct links), `test/dashboards.test.tsx`
(split view, detach, "Add widget" beside a session), and unit tests for `layout.ts`,
`agent-turns.ts` and the events; existing tests were updated for the new names and the
lazily read pipeline. `src/test/setup.ts` adds what jsdom lacks for Radix, cmdk and the
sidebar, and longer async timeouts (whole routes on a busy machine).

## Known gaps

- The dashboard half beside a session is read only; editing the layout happens on the
  dashboard page.
- In the one-column grid (narrow container, including a laptop with the agent panel
  open) there are no handles: "Edit layout" there only explains how.
- The record renders an agent's text as plain text (no Markdown yet).
- Moving a slot changes the DOM order after the save (reading order), which reloads the
  moved frames once.
