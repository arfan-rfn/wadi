"""Persisted data-model shapes recovered from ORM/ODM code (§7).

The recovered shape is the ORM shape, not true DDL — accepted for v1 (§12).

Since 1.26.0 (§5.2.17) a ``DataModel`` is the ENTITY RECORD: the type an
entity access names, with the names a query reader needs to find it (the
qualified class name, the JPQL name, the storage name) and how it came to be
an entity. **Reader migration (pre-1.26.0 documents):** every new field
defaults to None, which means "not recorded", never "absent from the code".
"""

from pydantic import Field

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.entity_access import EntityDeclaredBy


class DataModelField(WadiModel):
    name: str = Field(min_length=1)
    type_name: str | None = None
    declared_type: str | None = Field(
        default=None,
        description=(
            "1.26.0: the field's type as written in source, generics kept, e.g. "
            "'List<Release>'. `type_name` stays erased; a JPQL join target "
            "resolves through this one, because the element type is the entity "
            "the join reaches (§5.2.17)"
        ),
    )
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
    type_full_name: str | None = Field(
        default=None,
        description=(
            "1.26.0: the qualified class name, e.g. 'com.acme.orders.Order'. "
            "`id` derives from it when the export carries it, so two classes "
            "sharing a simple name in one service get two ids (C2). None on a "
            "pre-1.26.0 document"
        ),
    )
    jpql_name: str | None = Field(
        default=None,
        description="1.26.0: the `@Entity(name=...)` value when set — the name JPQL uses",
    )
    fields: list[DataModelField] = Field(default_factory=list[DataModelField])
    relations: list[DataModelRelation] = Field(default_factory=list[DataModelRelation])
    persistence_framework: str = Field(min_length=1, description="e.g. 'spring-data-mongodb'")
    storage_name: str | None = Field(
        default=None,
        description=(
            "Collection/table name where recoverable: `@Table(name=)` or "
            "`@Document`. Populated since 1.26.0; native SQL resolves its table "
            "names through it (§5.2.17)"
        ),
    )
    declared_by: EntityDeclaredBy | None = Field(
        default=None,
        description=(
            "1.26.0: how this type came to be an entity — `annotation` "
            "(@Entity/@Document) or `repository-argument` (a repository's type "
            "argument names it and it carries no annotation, Q1). None = a "
            "pre-1.26.0 document, which recorded neither"
        ),
    )
