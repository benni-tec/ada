# Text widgets with named inputs, and judges: implementation plan

> **Planned, not started (2026-11-14).** The user decided the order:
> 1. Named widget inputs come first, built by the platform agent (migration 0010:
>    `widgets.inputs` JSONB, plus `widgets.render_error` for wave 6).
> 2. Then wave 6 and this plan's tasks 2–6 run in parallel.
>
> Task 1 below is therefore the platform agent's; this plan builds on its merged contract,
> which the platform agent sends when it lands. Judges are configured in the Settings
> modal, not the sidebar. The remaining open decisions at the end are the user's.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reports and dashboards get headings and explanations as a Markdown **text widget**. Every figure in it comes from a pipeline: the widget references several operators through **named inputs**, and the Markdown pulls values from them with placeholders. A project-level **judge** (a "decision model", one of the configured LLMs) then reads each text widget and flags any figure or claim that no input backs. Judges are one generic review service with a kind per thing judged. Besides text widgets (`text_widget`), they review wave 6's custom-widget code for embedded data (`widget_code`). Judges are configured in Settings › This project › Judges.

**Why:** Report text is plain today (`Text` in `B/core/services/reports/content.py:52`), and the rule "numbers stay in widgets" is only a request in tool descriptions. A text widget makes prose first-class and keeps the rule. Its placeholders make numbers traceable by construction, and the judge catches what the deterministic check cannot: a literal number typed into the prose, or a sentence that contradicts its own data.

**Architecture:**
- **Named inputs:** `Widget.inputs: dict[str, OperatorId]`, alongside the existing `operator_id`, which stays the default input called `main`. One run serves all inputs of a view, as the existing rule requires.
- **Text widget:** a new widget type `text` with `spec = {markdown}` and placeholders `{{input.column}}`, checked against the inputs' schemas at creation. It is a new bundle in `W/widgets/text/`.
- **Judges:** a use case `JudgeService.review(project_id, kind, content, context) -> Verdict` (contract in task 4) on an outbound `JudgeModel` port. Its pydantic-ai adapter returns structured findings (`output_type`, no tools). Callers store the verdict on what they judged (`widgets.verdict`). Per-project settings per kind (strictness, model, instructions) live in a new `project_judges` table.

**Tech Stack:** Python 3.14, FastAPI, FastMCP, pydantic-ai, dishka, SQLAlchemy + Alembic, taskiq; React + TanStack Router + openapi-fetch; widget bundles (Vite, one HTML per type); moon.

**Paths:** `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`, `W/` = `services/widgets/src/`.

**Naming:** "slot" already means three things (a dashboard `Slot`, a report-template `slot`, an input operator). This plan says **input** for a widget's named operator references.

## Global Constraints

- Hexagonal layout as in `docs/contracts.md`: port Protocol in `B/core/ports/`, adapter in `B/adapters/<name>/`, dishka provider in `B/composition/providers/`, fake in `T/fakes.py`. Models, ports, `tables.py` and the migration change in one integration step (contracts.md, "Frozen code").
- One migration: `B/adapters/db/migrations/versions/0012_widget_inputs_and_judges.py`, revision `"0012"`, down_revision `"0011"`. The platform agent expects wave 6 to take 0010 and 0011; whoever merges second renumbers.
- No test reaches the network or calls a real model. The judge adapter is tested with pydantic-ai's `TestModel`/`FunctionModel`, and services with a `FakeJudge` in `T/fakes.py`.
- `moon run :lint :format :typecheck :test` before every commit. Tests go in the existing feature files (`T/test_widgets*.py`, `T/test_reports*.py`, `T/test_agent.py`); a new `T/test_judges.py` is allowed. Regenerate the frontend client (`moon run frontend:generate`) after REST changes.
- Commit messages in the repo's style (short imperative subjects).
- Existing widgets and reports must behave exactly as before: `operator_id` remains, and a widget without `inputs` has the single input `main`.

## Review Focus

1. **Traceability holds:**
   - a text widget whose placeholder names a missing input or column is refused at creation, with every problem named;
   - a frozen report version renders the frozen spec and run, never the widget's later spec;
   - `sources` lists the sources of every input.
2. **One run per view:** all inputs of a widget read the same run. A placeholder on a stale or simulated input is marked as such, exactly like a value widget.
3. **No injection:**
   - Markdown is sanitised: no raw HTML, scripts, iframes or images from outside;
   - placeholder values are escaped;
   - the judge's prompt treats the Markdown and the rows as data, never as instructions to the judge.
4. **The judge fails safe:**
   - no model configured or a provider error gives the verdict `unchecked`, never `pass`;
   - `block` strictness stops a report version only on `fail`, never on `unchecked`;
   - a stale verdict (spec or run changed) is never shown as current.
5. **Existing data:** the migration runs on the dev database with the seeded project, existing widgets get no `widget_inputs` rows, and every report version still renders.

---

### Task 1: Named widget inputs (done by the platform agent: f30da72, migration 0010)

This is the merged contract that tasks 2–6 build on:

- **Model** (`B/core/models/widgets.py`):
  - `MAIN_INPUT = "main"` is the widget's own `operator_id`.
  - `Widget.inputs: dict[str, OperatorId] = {}` holds further operators by name. Names match `^[a-z][a-z0-9_]{0,31}$` and are never `main`. There are at most 8 (`MAX_INPUTS`), all in the widget's project.
  - `Widget.all_inputs()` gives `{"main": operator_id, **inputs}`.
  - `Widget.render_error: str | None`.
- **Service:** `WidgetService.create(..., inputs=None)`/`update(..., inputs=None)`. On update, new inputs replace the old ones whole, and `{}` clears them. `WidgetService._inputs` checks them and raises `Invalid`.
- **Data:** `WidgetService.data(id, run_id=None, limit=1000, input="main")` returns `WidgetData` with `.input`. Read the other inputs of the same view by passing the first answer's `run_id`. REST: `GET /api/widgets/{id}/data?run_id=&limit=&input=`.
- **MCP:** `create_widget`/`update_widget` take `inputs`, and `get_widget_data` takes `input`. `build_pipeline` widget steps take `inputs: {name: id or $ref}`.
- **Reports and dashboards:** reports freeze every input of every widget, and dashboard copies keep their inputs.
- **Built-in types ignore inputs.** The text widget is the first type that reads them.
- **The judge port is already on main** (fea6b88). `B/core/models/judges.py` has the verdict models (no settings yet). `B/core/services/ports/judges.py` has `JudgeService.review`. `B/core/services/judges/unchecked.py` has `UncheckedJudges` and `content_hash(content, context)`, and `B/composition/providers/judges.py` binds the stub. Task 4 adds the settings models and methods, then rebinds the provider to the real service. Wave 6 adds `widgets.verdict` (JSONB) and `Widget.verdict` in its migration 0011, and migration 0012 reuses them.

### Task 2: The text widget type (backend)

**Files:**
- Create: `B/core/services/widgets/text.py`. It holds the placeholder grammar and checks, shared by the check and by the judge's prompt builder.
- Modify: `B/core/services/schema/roles.py` (`_NEEDS["text"] = _text`; a text widget needs at least one input, and `main` may be absent for a text widget), `B/entrypoints/mcp/tools/widgets.py` (the `text` row of the spec documentation), `B/entrypoints/mcp/server.py` `INSTRUCTIONS` and `B/core/services/agents/briefing.py` (headings and explanations go in text widgets; figures only through placeholders)
- Modify: `B/core/services/reports/service.py`. A report version stores each widget's type, spec and title at freezing, so the version renders the frozen text. Wave 6 freezes custom-widget code the same way, so reuse that mechanism if it has landed.

**Spec:** `{"markdown": str}`, at most 20,000 characters. CommonMark plus GFM tables, without raw HTML or images.

**Placeholders:**

| Form | Shows |
| --- | --- |
| `{{gap.value}}` | the column `value` of input `gap`: the latest period when the input has a time role, otherwise its single row (more rows without a time role is an error) |
| `{{gap.value:percent}}`, `:integer`, `:number1`, `:plain`, `:signed1` | the same value, formatted with the platform's number formats |
| `{{gap.value[county=Kainuu]}}` | the row where `county` equals `Kainuu` (exactly one row, or an error) |
| `{{gap}}` | the whole input as a compact table (at most 50 rows; the `table` widget's formats) |

**Check at creation** (deterministic; refused with every problem named):
- the input exists and the column exists in its output;
- a format suits the column type;
- a row filter names an existing column;
- an unused input is a warning, not an error.

- [ ] **Step 1:** Failing tests for the parser (each form, escaping `\{{`), for the check (unknown input, unknown column, a non-numeric column with a number format) and for freezing (a version keeps its Markdown after `update_widget`).
- [ ] **Step 2:** Implement, update the tool docs, instructions and briefing. Run the checks, then commit.

### Task 3: The text widget bundle and content-sized frames (frontend)

**Files:**
- Create: `W/widgets/text/index.html`, `main.tsx`, `text.tsx`. Register the type in `W/widgets/any/any.tsx` `TYPES`.
- Modify: `W/lib/runtime.tsx` (per-value flags), `F/lib/widgets.ts` (the `heights` entry), `F/components/widget-card.tsx` and `F/components/reports/report-tree.tsx` (frames sized to content)

**Rendering:**
- Use the same Markdown renderer as chat (`streamdown`, as in `F/components/chat/markdown.tsx`), sanitised.
- Each placeholder becomes the formatted value in a quiet, tabular style. Its tooltip shows the input, column, run and fetch time, and clicking it opens that input in the pipeline dialog.
- A stale or simulated input marks its values the way `Flags` does.
- An error (a missing row, for example) shows inline as a muted "no value" with the reason in the tooltip, never as a blank.

**Content-sized frames:** the bundle posts its height (`ada:resize`, via `host.ts`), and cards in reports and the session column follow it. Dashboard cards keep their grid height and scroll inside. This also fixes the fixed-height report frames reported today (squashed heatmaps, blank space under short tables).

- [ ] **Step 1:** Widget tests (a render with two inputs, formats, flags, an error case, no raw HTML).
- [ ] **Step 2:** Implement the bundle and the resize protocol. Check a report and a dashboard in the browser in light and dark mode. Run the checks, then commit.

### Task 4: Judges (backend): one generic service, one kind per thing judged

Judges are a generic review service, not a text-only feature (the user's decision). Each **kind** has its own prompt, its own on/off switch and strictness, and its own model. The first two kinds are:

| Kind | Content | Context | Flags |
| --- | --- | --- | --- |
| `text_widget` | a text widget's Markdown, with each placeholder resolved and tagged, e.g. `⟦gap.value = 13.2⟧` | the widget's inputs: columns and up to 200 rows each | a figure that is neither a resolved placeholder nor a non-measurement (a target or threshold stated as such, a year, a count of named things, a method parameter); a statement its inputs contradict; a comparative claim its inputs cannot decide (warning only) |
| `widget_code` | a wave 6 custom widget's code (the ES module, and its CSS) | the widget's inputs: columns, and up to 20 rows each | literal data in the code: arrays or objects of numbers, hard-coded labels or values that should come from inputs, values copied from the rows; not layout constants (sizes, margins, ticks, colours) |

**Contract** (fixed; wave 6 builds against it, so change it only together with the platform agent):

```python
# B/core/models/judges.py
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from ada.core.models.base import DomainModel, Id
from ada.core.models.schema import Column


class JudgeKind(StrEnum):
    TEXT_WIDGET = "text_widget"
    WIDGET_CODE = "widget_code"


class Strictness(StrEnum):
    OFF = "off"      # never reviewed: the verdict is unchecked
    WARN = "warn"    # reviewed and shown; never blocks
    BLOCK = "block"  # reviewed; a failed verdict is blocking


class Outcome(StrEnum):
    PASS = "pass"            # no findings
    WARN = "warn"            # only warnings
    FAIL = "fail"            # at least one error
    UNCHECKED = "unchecked"  # off, no model chosen, or the model call failed


class JudgeInput(DomainModel):
    """One named input of the thing judged, as the judge may see it."""

    name: str
    columns: tuple[Column, ...]
    rows: tuple[tuple[Any, ...], ...] = ()  # a sample; the service caps it per kind


class JudgeContext(DomainModel):
    inputs: tuple[JudgeInput, ...] = ()
    note: str = ""  # what the content is, e.g. the widget's type and title


class Finding(DomainModel):
    message: str  # what is wrong and what to do instead
    excerpt: str  # the exact text of the content it is about
    severity: Literal["error", "warning"] = "error"


class Verdict(DomainModel):
    kind: JudgeKind
    outcome: Outcome
    passed: bool    # outcome is pass or warn; unchecked is not passed
    blocking: bool  # strictness is block and outcome is fail
    findings: tuple[Finding, ...] = ()
    model: str | None = None   # "<provider>/<model>", None when unchecked
    reason: str | None = None  # why it is unchecked
    content_hash: str          # sha256 of content and context: a verdict is current only for these
    checked_at: datetime


class JudgeDefaults(DomainModel):
    """The global settings of one kind, beside the global LLM registry."""

    kind: JudgeKind
    strictness: Strictness = Strictness.WARN
    model_id: str | None = None  # "<provider>/<model>" from the configured models
    instructions: str = ""       # added to the kind's prompt in every project
    revision: int = 0


class JudgeOverride(DomainModel):
    """A project's overrides of one kind; None inherits the global default."""

    project_id: Id
    kind: JudgeKind
    strictness: Strictness | None = None
    model_id: str | None = None
    instructions: str | None = None  # project instructions come after the global ones
    revision: int = 0


class JudgeSettings(DomainModel):
    """What review uses in a project: the defaults with the project's overrides applied."""

    project_id: Id
    kind: JudgeKind
    strictness: Strictness
    model_id: str | None
    instructions: str  # global, then project
    overridden: frozenset[str] = frozenset()  # the fields the project overrides


# B/core/services/ports/judges.py
class JudgeService(Protocol):
    async def review(
        self, project_id: Id, kind: JudgeKind, content: str, context: JudgeContext
    ) -> Verdict:
        """Review content with the project's judge of this kind. It never raises for the
        model: off, no model or a failed call gives an unchecked verdict with a reason. It
        raises NotFound for an unknown project. Results are cached by (content_hash,
        model, revisions of the defaults and the override). The caller stores the verdict on what it judged."""
        ...

    async def defaults(self) -> Sequence[JudgeDefaults]: ...  # one per kind
    async def set_defaults(
        self, kind: JudgeKind, expected_revision: int,
        strictness: Strictness | None = None, model_id: Change[str | None] = UNCHANGED,
        instructions: str | None = None,
    ) -> JudgeDefaults: ...

    async def settings(self, project_id: Id) -> Sequence[JudgeSettings]: ...  # effective, one per kind
    async def override(
        self, project_id: Id, kind: JudgeKind, expected_revision: int,
        strictness: Change[Strictness | None] = UNCHANGED,  # None: inherit again
        model_id: Change[str | None] = UNCHANGED,
        instructions: Change[str | None] = UNCHANGED,
    ) -> JudgeSettings: ...
```

**Outbound port:** `B/core/ports/judges.py` `JudgeModel.decide(model: ModelTarget, system: str, content: str, context: JudgeContext) -> tuple[Finding, ...]` (raises on a provider error; the service turns that into `unchecked`). The adapter `B/adapters/llm/judge.py` is a pydantic-ai `Agent(provider_model(target), output_type=JudgeOutput, model_settings={"temperature": 0})` without tools. The prompt wraps the content and the rows in delimited data blocks and tells the model they are data, never instructions.

**Storage:**
- Settings go in two tables in migration 0012:
  - `judge_defaults` (PK `kind`; `strictness`, `model_id` FK to `llm_models` `ON DELETE SET NULL`, `instructions`, `revision`). It is global, like `agent_settings` and the LLM registry, and is seeded with `warn` and no model for each kind.
  - `project_judges` (PK `project_id, kind`; nullable `strictness`, `model_id` and `instructions`, where NULL inherits; `revision`).

  A judge with no model in either place gives unchecked.
- Verdicts are stored by the caller on what they judge: `widgets.verdict` (JSONB, a `Verdict`) and `Widget.verdict: Verdict | None`. That column is shared with wave 6. Whichever migration merges first adds it (0011 if wave 6 is first), and the other reuses it.
- Until this task merges, wave 6 binds `JudgeService` to a stub whose `review` returns `unchecked` with the reason "judges are not built yet" (contracts.md, "unbuilt").

**Files:**
- Create: `B/core/models/judges.py`, `B/core/services/ports/judges.py`, `B/core/ports/judges.py`, `B/adapters/llm/judge.py`, `B/core/services/judges/service.py`, `B/core/services/judges/prompts.py` (one prompt per kind), `B/entrypoints/http/routers/judges.py`, `B/entrypoints/mcp/tools/judges.py`, `B/composition/providers/judges.py`, `T/test_judges.py`.
- Modify: `tables.py` and migration 0012 (`project_judges`), `T/fakes.py` (`FakeJudgeModel`), `B/core/services/widgets/` (text widgets: review on create and update, store the verdict), `B/core/services/reports/service.py` (review text widgets on the version's run before storing; a blocking verdict refuses the version and names the findings).

**Triggers for `text_widget`:**
- `create_widget`/`update_widget` reviews on the latest run. This runs in the worker task `judge_widget`, so the call returns at once with the previous or an unchecked verdict.
- Report versions review each text widget on the version's run before storing.
- A "Review again" action re-runs on demand.

`widget_code` is triggered by wave 6 (create and update of a custom widget).

**Surfaces:**
- the verdict is on the widget (`get_widget`, `update_widget`, the card badge, the agent's briefing);
- `GET /api/settings/judges` and `PUT /api/settings/judges/{kind}` (global defaults);
- `GET /api/projects/{id}/judges` (effective, with what is overridden) and `PUT /api/projects/{id}/judges/{kind}` (overrides; `null` inherits);
- `GET /api/projects/{id}/verdicts?kind=&outcome=` (widgets with a verdict, newest first);
- the MCP tool `review_widget(widget_id, session_id)`.

- [ ] **Step 1:** Failing tests (`FakeJudgeModel`, and pydantic-ai `TestModel` for the adapter):
  - `text_widget`: a literal number in the prose fails, and a resolved placeholder passes;
  - `widget_code`: a literal array of numbers fails, and layout constants pass;
  - strictness: `off` gives unchecked; no model gives unchecked with a reason; a provider error gives unchecked;
  - `block`: a fail is blocking and refuses a report version, while unchecked never blocks;
  - caching: the same content and context makes one model call, and a new revision of the defaults or the override makes a new one;
  - inheritance: a project without overrides uses the global defaults; an override wins; setting it to null inherits again; project instructions come after global ones;
  - safety: the prompt marks the content and the rows as data.
- [ ] **Step 2:** Implement the models, ports, adapter, prompts, service, worker task, routes and tool. Run the checks, then commit.

### Task 5: Judges (frontend)

**Files:**
- Create: `F/components/settings/judges.tsx` (`GlobalJudgesSection` and `ProjectJudgesSection`, built from `Field` and `SettingsSection` in `form.tsx`), `F/lib/api/judges.ts`.
- Modify:
  - `F/lib/settings-sections.ts`: add `judges` to `globalSections` (after `models`) and `project-judges` to `projectSections` (after `project-instructions`).
  - `F/components/settings/settings-modal.tsx`: render the section in the `Section` switch.
  - the project layout route's validated `settings` search param: accept `?settings=judges` and `?settings=project-judges`.
  - `F/components/widget-card.tsx` and `F/components/reports/report-tree.tsx`: the verdict badge.

**The Judges sections** sit in the Settings modal (the gear), not in the sidebar, in the same layout as the LLM registry: global defaults under "Global", overrides under "This project".

- **Global › Judges** (`?settings=judges`) has one card per kind: "Text widgets" (`text_widget`) and "Custom widget code" (`widget_code`). Each card has:
  - the strictness (Off / Warn / Block), default Warn, with one line on what each does;
  - the model, chosen from the configured models (`GET /llm/models`), with a link to Global › Models when none exists;
  - instructions added to the kind's prompt in every project.
- **This project › Judges** (`?settings=project-judges`) shows the same cards with the effective values.
  - Each field says "Global default" until it is overridden, and has a "Use global default" action to clear the override.
  - Project instructions are added after the global ones.
  - The card lists that kind's recent verdicts in the project: widget, outcome, findings count, time, and a link to the widget.

**Badge:** text and custom widgets show "Reviewed ✓", "2 findings" (warn or fail) or "Not reviewed". The badge opens the findings, each with its excerpt and message. On custom widgets it sits next to wave 6's render error.

- [ ] **Step 1:** Route and component tests (page loads and saves; the badge shows each outcome).
- [ ] **Step 2:** Implement, regenerate the client, and check in the browser. Run the checks, then commit.

### Task 6: Integration

- [ ] Fold the contract into `docs/contracts.md` (text type, judges, REST, MCP, worker task, the `?settings=judges` section) and add a section to `docs/plan.md`.
- [ ] Turn the "Data quality review" report into a version that uses text widgets for its explanations, and check that the judge passes it.
- [ ] Tell the platform agent the final migration number.

## Decisions (the user's, 2026-11-14)

1. **Order:** the platform agent builds named inputs first; then wave 6 and tasks 2–6 run in parallel.
2. **Report text and callout blocks stay as they are.** Report templates keep using them, so templates never need to reference text widgets. Text widgets are added beside them for prose that carries figures.
3. **Strictness defaults to Warn** and is configurable. The global defaults sit next to the global LLM registry, and each project may override strictness, model and instructions per kind.
4. **The text judge checks both** unbacked figures and statements that contradict the data (or that the data cannot decide).
5. **Markdown:** no images, no raw HTML; links are allowed and open in a new tab.
