"""Judges: a language model reviews what agents wrote before people see it.

One generic service, a kind per thing judged (JudgeKind), each with its own prompt
(prompts.py) and settings: global defaults, which a project may override per field. The
service never raises for the model: a judge that is off, has no model, or whose call
fails gives an unchecked verdict with the reason, which never passes and never blocks.
"""

import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime

from ada.core.models.base import UNCHANGED, Change, Id, Unchanged
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.judges import (
    Finding,
    JudgeContext,
    JudgeDefaults,
    JudgeInput,
    JudgeKind,
    JudgeOverride,
    JudgeSettings,
    Outcome,
    Strictness,
    Verdict,
)
from ada.core.ports.agents import LanguageModels
from ada.core.ports.judges import JudgeModel
from ada.core.ports.repositories import (
    JudgeSettingsRepository,
    LlmModelRepository,
    ProjectRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.judges.prompts import ROWS, system_prompt
from ada.core.services.ports.judges import JudgeService

logger = logging.getLogger(__name__)

MAX_INSTRUCTIONS = 20_000
_FIELDS = ("strictness", "model_id", "instructions")

type CacheKey = tuple[str, str, int, int]


def content_hash(content: str, context: JudgeContext) -> str:
    """sha256 of the content and its context, the key a verdict is cached by."""
    payload = json.dumps([content, context.model_dump(mode="json")], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class VerdictCache:
    """Verdicts the model gave, by (content hash, model, revision of the defaults, revision
    of the override): the same content under the same settings is not reviewed twice. One
    per process, holding the most recent MAX entries."""

    MAX = 1_000

    def __init__(self) -> None:
        self._verdicts: OrderedDict[CacheKey, Verdict] = OrderedDict()

    def get(self, key: CacheKey) -> Verdict | None:
        verdict = self._verdicts.get(key)
        if verdict is not None:
            self._verdicts.move_to_end(key)
        return verdict

    def put(self, key: CacheKey, verdict: Verdict) -> None:
        self._verdicts[key] = verdict
        self._verdicts.move_to_end(key)
        while len(self._verdicts) > self.MAX:
            self._verdicts.popitem(last=False)


class Judges(JudgeService):
    def __init__(
        self,
        settings: JudgeSettingsRepository,
        projects: ProjectRepository,
        models: LlmModelRepository,
        language_models: LanguageModels,
        model: JudgeModel,
        cache: VerdictCache,
        clock: Clock,
    ) -> None:
        self.store = settings
        self.projects = projects
        self.models = models
        self.language_models = language_models
        self.model = model
        self.cache = cache
        self.clock = clock

    async def review(
        self, project_id: Id, kind: JudgeKind, content: str, context: JudgeContext
    ) -> Verdict:
        await self.projects.get(project_id)
        defaults, override = await self._records(project_id, kind)
        effective = _effective(project_id, defaults, override)
        context = _capped(context, ROWS[kind])
        hashed = content_hash(content, context)

        def unchecked(reason: str) -> Verdict:
            return Verdict(
                kind=kind,
                outcome=Outcome.UNCHECKED,
                passed=False,
                blocking=False,
                reason=reason,
                content_hash=hashed,
                checked_at=self.clock.now(),
            )

        if effective.strictness is Strictness.OFF:
            return unchecked("the judge is off")
        if effective.model_id is None:
            return unchecked("no model is chosen for this judge")
        key = (hashed, effective.model_id, defaults.revision, override.revision)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            target = await self.language_models.target(effective.model_id)
        except Invalid as error:
            return unchecked(f"the judge's model cannot be used: {error}")
        try:
            findings = await self.model.decide(
                target, system_prompt(kind, effective.instructions), content, context
            )
        except Exception as error:
            # Never passes for a failed call: the content is shown unchecked.
            logger.warning("The %s judge's model call failed: %s", kind.value, error)
            return unchecked(f"the judge's model call failed: {_short(error)}")
        verdict = _verdict(kind, effective, tuple(findings), hashed, self.clock.now())
        self.cache.put(key, verdict)
        return verdict

    # Settings

    async def defaults(self) -> Sequence[JudgeDefaults]:
        stored = {defaults.kind: defaults for defaults in await self.store.defaults()}
        return [stored.get(kind, JudgeDefaults(kind=kind)) for kind in JudgeKind]

    async def set_defaults(
        self,
        kind: JudgeKind,
        expected_revision: int,
        strictness: Strictness | None = None,
        model_id: Change[str | None] = UNCHANGED,
        instructions: str | None = None,
    ) -> JudgeDefaults:
        current = next(d for d in await self.defaults() if d.kind is kind)
        changes: dict[str, object] = {}
        if strictness is not None:
            changes["strictness"] = strictness
        if not isinstance(model_id, Unchanged):
            changes["model_id"] = await self._model(model_id)
        if instructions is not None:
            changes["instructions"] = _instructions(instructions)
        return await self.store.update_defaults(
            current.model_copy(update=changes), expected_revision
        )

    async def settings(self, project_id: Id) -> Sequence[JudgeSettings]:
        await self.projects.get(project_id)
        overrides = {o.kind: o for o in await self.store.overrides(project_id)}
        return [
            _effective(
                project_id,
                defaults,
                overrides.get(
                    defaults.kind, JudgeOverride(project_id=project_id, kind=defaults.kind)
                ),
            )
            for defaults in await self.defaults()
        ]

    async def override(
        self,
        project_id: Id,
        kind: JudgeKind,
        expected_revision: int,
        strictness: Change[Strictness | None] = UNCHANGED,
        model_id: Change[str | None] = UNCHANGED,
        instructions: Change[str | None] = UNCHANGED,
    ) -> JudgeSettings:
        await self.projects.get(project_id)
        defaults, current = await self._records(project_id, kind)
        changes: dict[str, object] = {}
        if not isinstance(strictness, Unchanged):
            changes["strictness"] = strictness
        if not isinstance(model_id, Unchanged):
            changes["model_id"] = await self._model(model_id)
        if not isinstance(instructions, Unchanged):
            changes["instructions"] = (
                _instructions(instructions) if instructions is not None else None
            )
        saved = await self.store.save_override(
            current.model_copy(update=changes), expected_revision
        )
        return _effective(project_id, defaults, saved)

    async def _records(
        self, project_id: Id, kind: JudgeKind
    ) -> tuple[JudgeDefaults, JudgeOverride]:
        defaults = next(d for d in await self.defaults() if d.kind is kind)
        override = next(
            (o for o in await self.store.overrides(project_id) if o.kind is kind),
            JudgeOverride(project_id=project_id, kind=kind),
        )
        return defaults, override

    async def _model(self, model_id: str | None) -> str | None:
        if model_id is None:
            return None
        try:
            return (await self.models.get(model_id)).id
        except NotFound:
            raise Invalid(f"No model {model_id!r} is configured") from None


def _effective(project_id: Id, defaults: JudgeDefaults, override: JudgeOverride) -> JudgeSettings:
    overridden = frozenset(field for field in _FIELDS if getattr(override, field) is not None)
    instructions = "\n\n".join(
        text
        for text in (defaults.instructions.strip(), (override.instructions or "").strip())
        if text
    )
    return JudgeSettings(
        project_id=project_id,
        kind=defaults.kind,
        strictness=override.strictness or defaults.strictness,
        model_id=override.model_id if override.model_id is not None else defaults.model_id,
        instructions=instructions,
        overridden=overridden,
        revision=override.revision,
    )


def _verdict(
    kind: JudgeKind,
    settings: JudgeSettings,
    findings: tuple[Finding, ...],
    hashed: str,
    at: datetime,
) -> Verdict:
    if any(finding.severity == "error" for finding in findings):
        outcome = Outcome.FAIL
    elif findings:
        outcome = Outcome.WARN
    else:
        outcome = Outcome.PASS
    return Verdict(
        kind=kind,
        outcome=outcome,
        passed=outcome in (Outcome.PASS, Outcome.WARN),
        blocking=settings.strictness is Strictness.BLOCK and outcome is Outcome.FAIL,
        findings=findings,
        model=settings.model_id,
        content_hash=hashed,
        checked_at=at,
    )


def _capped(context: JudgeContext, rows: int) -> JudgeContext:
    return context.model_copy(
        update={
            "inputs": tuple(
                JudgeInput(name=i.name, columns=i.columns, rows=i.rows[:rows])
                for i in context.inputs
            )
        }
    )


def _instructions(text: str) -> str:
    text = text.strip()
    if len(text) > MAX_INSTRUCTIONS:
        raise Invalid(f"Judge instructions are at most {MAX_INSTRUCTIONS:,} characters")
    return text


def _short(error: Exception) -> str:
    text = str(error) or type(error).__name__
    return text if len(text) <= 300 else text[:300] + "…"
