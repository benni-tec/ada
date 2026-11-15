"""The project's pipelines as a list a person picks from: the operators nothing builds on,
each named so that it can be recognised without reading its SQL."""

import re
from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from ada.core.models.base import Id
from ada.core.models.operators import Operator, OperatorId, OperatorKind
from ada.core.models.pipelines import Pipeline, PipelineSource

# Long enough to tell pipelines apart in a dropdown, short enough to fit in one.
MAX_NAME_LENGTH = 60


def pipelines(operators: Sequence[Operator], source_names: Mapping[Id, str]) -> list[Pipeline]:
    """The operators that no other operator uses as an input, newest first."""
    by_id = {operator.id: operator for operator in operators}
    used = {input_id for operator in operators for input_id in operator.inputs}
    roots = [operator for operator in operators if operator.id not in used]
    roots.sort(key=lambda operator: (operator.created_at, operator.id), reverse=True)
    return [
        Pipeline(
            operator_id=root.id,
            name=name(root, source_names),
            kind=root.kind,
            sources=tuple(
                PipelineSource(data_source_id=source_id, name=source_names.get(source_id, ""))
                for source_id in _sources(root, by_id)
            ),
            output=root.output,
            created_at=root.created_at,
        )
        for root in roots
    ]


def name(operator: Operator, source_names: Mapping[Id, str]) -> str:
    match operator.kind:
        case OperatorKind.SOURCE:
            source_id = _source_id(operator)
            return source_names.get(source_id, str(source_id)) if source_id else operator.id
        case OperatorKind.TRANSFORM:
            return sql_name(str(operator.params.get("sql", ""))) or operator.id
        case OperatorKind.INPUT:
            return str(operator.params.get("name", "")) or operator.id
        case OperatorKind.STATISTIC:
            return sql_name(str(operator.params.get("sql", ""))) or operator.id
        case _:
            return f"{operator.kind.value} {operator.id}"


def sql_name(sql: str) -> str:
    """A leading comment says what the SQL is for, when there is one; otherwise its first
    words, which name the columns it selects."""
    lines = sql.strip().splitlines()
    comments = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("--"):
            break
        comments.append(stripped.removeprefix("--").strip())
    words = " ".join(comment for comment in comments if comment) or " ".join(sql.split())
    return _shortened(words)


def _shortened(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= MAX_NAME_LENGTH:
        return text
    cut = text[: MAX_NAME_LENGTH - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",") + "…"


def _sources(root: Operator, by_id: Mapping[OperatorId, Operator]) -> Iterable[Id]:
    """The data sources upstream of `root`, each once, inputs first and in order. A source
    reached twice (a diamond) is still listed once."""
    seen: set[OperatorId] = set()
    found: list[Id] = []

    def visit(operator_id: OperatorId) -> None:
        if operator_id in seen or operator_id not in by_id:
            return
        seen.add(operator_id)
        operator = by_id[operator_id]
        for input_id in operator.inputs:
            visit(input_id)
        source_id = _source_id(operator)
        if source_id is not None and source_id not in found:
            found.append(source_id)

    visit(root.id)
    return found


def _source_id(operator: Operator) -> Id | None:
    if operator.kind is not OperatorKind.SOURCE:
        return None
    return UUID(str(operator.params["data_source_id"]))
