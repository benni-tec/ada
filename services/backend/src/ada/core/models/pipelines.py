from datetime import datetime

from ada.core.models.base import DomainModel, Id
from ada.core.models.operators import OperatorId, OperatorKind
from ada.core.models.schema import Schema


class PipelineSource(DomainModel):
    data_source_id: Id
    name: str


class Pipeline(DomainModel):
    """An operator no other operator uses as an input, with what it reads: a pipeline a
    person can put a widget on or an agent can build on."""

    operator_id: OperatorId
    # Readable: the source's name, the SQL's leading comment or first words, the input
    # slot's name.
    name: str
    kind: OperatorKind
    # The data sources upstream, each once, in the order the pipeline reads them.
    sources: tuple[PipelineSource, ...] = ()
    output: Schema
    created_at: datetime
