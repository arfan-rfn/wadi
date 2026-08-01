"""Persisted data-model shapes recovered from ORM/ODM code (§7).

The recovered shape is the ORM shape, not true DDL — accepted for v1 (§12).
"""

from pydantic import Field

from wadi_contracts.base import ArtifactEnvelope, WadiModel


class DataModelField(WadiModel):
    name: str = Field(min_length=1)
    type_name: str | None = None
    nullable: bool | None = Field(
        default=None, description="None = not statically determinable (P10)"
    )


class DataModelRelation(WadiModel):
    kind: str = Field(min_length=1, description="e.g. 'one-to-many', 'embedded', 'reference'")
    target_entity: str = Field(min_length=1)
    field: str | None = None


class DataModel(ArtifactEnvelope):
    """One persisted entity of one service."""

    id: str = Field(pattern=r"^dm_[0-9a-f]{16}$")
    entity: str = Field(min_length=1, description="Entity/class name, e.g. 'Order'")
    fields: list[DataModelField] = Field(default_factory=list[DataModelField])
    relations: list[DataModelRelation] = Field(default_factory=list[DataModelRelation])
    persistence_framework: str = Field(min_length=1, description="e.g. 'spring-data-mongodb'")
    storage_name: str | None = Field(
        default=None, description="Collection/table name where recoverable"
    )
