"""The query reader (M6, §5.2.17): an annotated query's text decides what it does.

Table tests through the classifier's one public seam, :func:`classify_db_access`,
with the query written inline the way a repository method carries it. Each
class is one rule of the plan's "Query reader (M6)" (R1-24, C1): which reader
a query goes to, its verb, the names it resolves, one access per entity, and
what it says when a name does not resolve. Every site is on the ``query-text``
basis, which no gate flag holds back: its verbs publish directly.
"""

import pytest

from wadi_contracts import (
    DataModel,
    DataModelField,
    EntityAccessBasis,
    EntityAccessSite,
    EntityOperation,
    data_model_id,
)
from wadi_joern_client.export import ExportDbAccess, ExportDbQuery, RepositoryKind
from wadi_worker.entity_access import classify_db_access
from wadi_worker.query_reader import EntityCatalog

SVC = "svc_" + "a" * 16
SHOP = "com.acme.shop"
ORDER = f"{SHOP}.Order"
ORDER_LINE = f"{SHOP}.OrderLine"
CUSTOMER = f"{SHOP}.Customer"
INVOICE = f"{SHOP}.Invoice"
ORDER_REPO = f"{SHOP}.OrderRepository"

C, R, U, D = (
    EntityOperation.CREATE,
    EntityOperation.READ,
    EntityOperation.UPDATE,
    EntityOperation.DELETE,
)
UNK = EntityOperation.UNKNOWN


def _model(
    full_name: str,
    *,
    jpql_name: str | None = None,
    storage_name: str | None = None,
    storage_schema: str | None = None,
    fields: tuple[tuple[str, str, str], ...] = (),
) -> DataModel:
    """An entity record; each field is (name, erased type_name, declared_type)."""
    return DataModel(
        snapshot_id="snap_" + "b" * 16,
        service_id=SVC,
        id=data_model_id(SVC, full_name),
        entity=full_name.rsplit(".", 1)[-1],
        type_full_name=full_name,
        jpql_name=jpql_name,
        storage_name=storage_name,
        storage_schema=storage_schema,
        fields=[
            DataModelField(name=name, type_name=type_name, declared_type=declared)
            for name, type_name, declared in fields
        ],
        persistence_framework="spring-data",
    )


SHOP_ENTITIES = EntityCatalog(
    [
        _model(
            ORDER,
            storage_name="orders",
            fields=(
                ("id", "java.lang.String", "String"),
                ("customer", CUSTOMER, "Customer"),
                ("lines", "java.util.List", "List<OrderLine>"),
            ),
        ),
        _model(ORDER_LINE, fields=(("order", ORDER, "Order"),)),
        _model(CUSTOMER, jpql_name="Client", storage_name="customers"),
        _model(INVOICE, storage_name="invoices", fields=(("customer", CUSTOMER, "Customer"),)),
    ]
)


ELEMENTS = EntityCatalog(
    [
        _model(
            ORDER,
            fields=(
                ("tags", "java.util.Set", "Set<String>"),
                ("items", "java.util.List", "List<LineItem>"),
                ("address", f"{SHOP}.Address", "Address"),
                ("notes", "java.util.Map", "Map<String, java.lang.String>"),
                ("raw", "java.util.List", "List"),
                ("qualified_raw", "java.util.Set", "java.util.Set"),
                ("wild", "java.util.List", "List<?>"),
                ("lines", "java.util.List", "List<OrderLine>"),
            ),
        ),
        _model(ORDER_LINE),
    ]
)
"""Order's paths to things that are not entities: basic values, an
embeddable `LineItem`, an embedded `Address`."""


def _query(
    text: str | None,
    *,
    native: bool = False,
    kind: RepositoryKind = RepositoryKind.JPA,
    entity: str | None = ORDER,
    modifying: bool = False,
) -> ExportDbAccess:
    """A repository method on ``OrderRepository`` carrying ``@Query(text)``,
    and ``@Modifying`` when ``modifying``."""
    return ExportDbAccess(
        repository=ORDER_REPO,
        method_name="findSomething",
        entity_type_text=entity.rsplit(".", 1)[-1] if entity else "E",
        entity_type_full_name=entity,
        repository_kind=kind,
        implemented_in_project=False,
        query=ExportDbQuery(text=text, native=native, modifying=modifying),
    )


def _read(db: ExportDbAccess, entities: EntityCatalog = SHOP_ENTITIES) -> EntityAccessSite:
    site = classify_db_access(db, entities=entities)
    assert site is not None
    assert site.basis is EntityAccessBasis.QUERY_TEXT
    return site


def _accesses(site: EntityAccessSite) -> list[tuple[str | None, EntityOperation]]:
    return [(access.entity, access.operation) for access in site.accesses]


class TestJpql:
    def test_a_select_reads_the_entity_it_names(self) -> None:
        site = _read(_query("select l from OrderLine l where l.sku = ?1"))

        assert _accesses(site) == [(ORDER_LINE, R)]
        assert site.accesses[0].data_model_id == data_model_id(SVC, ORDER_LINE)
        assert site.accesses[0].candidate_operation is None
        assert site.entity_type_text is None

    def test_a_modifying_update_updates_its_target(self) -> None:
        site = _read(_query("update Order o set o.status = ?2 where o.id = ?1", modifying=True))

        assert _accesses(site) == [(ORDER, U)]

    def test_a_delete_with_a_subquery_deletes_its_target_and_reads_the_other(self) -> None:
        # C1: one site, two accesses, each with the operation the statement
        # applies to that entity. `Client` is Customer's JPQL name.
        site = _read(
            _query(
                "delete from Invoice i where i.customer in "
                "(select c from Client c where c.vip = false)",
                modifying=True,
            )
        )

        assert _accesses(site) == [(INVOICE, D), (CUSTOMER, R)]
        assert [a.data_model_id for a in site.accesses] == [
            data_model_id(SVC, INVOICE),
            data_model_id(SVC, CUSTOMER),
        ]


class TestJpqlNames:
    """Rule 3: an entity is named by position, case-sensitively, through
    `@Entity(name=)` first and the simple class name second."""

    def test_an_entity_named_like_a_keyword_is_an_entity_by_position(self) -> None:
        # `Order` after `from` is the entity; `order by` is the clause.
        site = _read(_query("select o from Order o order by o.id"))

        assert _accesses(site) == [(ORDER, R)]

    def test_order_by_right_after_the_entity_is_not_taken_for_an_alias(self) -> None:
        site = _read(_query("SELECT o FROM Order ORDER BY o.id"))

        assert _accesses(site) == [(ORDER, R)]

    def test_each_declaration_of_a_comma_list_is_read(self) -> None:
        site = _read(_query("select o from Order o, Invoice i where i.customer = o.customer"))

        assert _accesses(site) == [(ORDER, R), (INVOICE, R)]

    def test_the_entity_name_matches_before_the_class_name(self) -> None:
        # A legacy class literally named `Client` and Customer's
        # `@Entity(name = "Client")`: the JPQL name decides.
        legacy_client = f"{SHOP}.legacy.Client"
        entities = EntityCatalog(
            [_model(CUSTOMER, jpql_name="Client"), _model(legacy_client, jpql_name="OldClient")]
        )

        assert _accesses(_read(_query("select c from Client c"), entities)) == [(CUSTOMER, R)]
        assert _accesses(_read(_query("select c from OldClient c"), entities)) == [
            (legacy_client, R)
        ]

    def test_a_class_that_set_an_entity_name_no_longer_answers_to_its_class_name(self) -> None:
        site = _read(_query("select c from Customer c"))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "Customer"

    def test_a_case_sensitive_miss_is_undetermined_and_keeps_the_name(self) -> None:
        # Never guessed from a similar name (rule 6, P10).
        site = _read(_query("select o from order o where o.status = ?1"))

        assert _accesses(site) == [(None, R)]
        assert site.accesses[0].data_model_id is None
        assert site.entity_type_text == "order"

    def test_a_name_two_entities_answer_to_is_undetermined(self) -> None:
        entities = EntityCatalog([_model(f"{SHOP}.billing.Account"), _model(f"{SHOP}.crm.Account")])
        site = _read(_query("select a from Account a"), entities)

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "Account"

    def test_several_unresolved_names_are_all_kept_as_the_text(self) -> None:
        site = _read(_query("select a from Archive a join Ledger g on g.id = a.id"))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "Archive, Ledger"

    def test_an_unresolved_name_beside_a_resolved_one_leaves_no_text(self) -> None:
        # The site names its unresolved text only when nothing resolved.
        site = _read(_query("select o from Order o join o.notAField x"))

        assert _accesses(site) == [(ORDER, R), (None, R)]
        assert site.entity_type_text is None

    def test_a_statement_that_names_no_entity_keeps_its_verb_undetermined(self) -> None:
        site = _read(_query("select count(o) where o.id = ?1"))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text is None


class TestOneAccessPerEntity:
    """Rule 5 (C1): the verb applies to the statement's target; every other
    entity a write statement names is read."""

    def test_an_insert_select_creates_its_target_and_reads_its_source(self) -> None:
        site = _read(_query("insert into Order (id, status) select l.id, 'NEW' from OrderLine l"))

        assert _accesses(site) == [(ORDER, C), (ORDER_LINE, R)]

    def test_one_entity_with_two_operations_keeps_both(self) -> None:
        site = _read(
            _query(
                "delete from Order o where o.id in "
                "(select p.id from Order p where p.status = 'DUPLICATE')"
            )
        )

        assert _accesses(site) == [(ORDER, D), (ORDER, R)]

    def test_one_entity_named_twice_with_one_operation_is_one_access(self) -> None:
        site = _read(_query("select a from Order a, Order b where a.customer = b.customer"))

        assert _accesses(site) == [(ORDER, R)]

    def test_a_join_of_a_write_statement_is_read(self) -> None:
        site = _read(
            _query(
                "update orders o join customers c on c.id = o.customer_id set o.status = 'VIP'",
                native=True,
            )
        )

        assert _accesses(site) == [(ORDER, U), (CUSTOMER, R)]


class TestDeclarationShapes:
    def test_a_from_inside_a_function_names_nothing(self) -> None:
        site = _read(
            _query(
                "select o from Order o where extract(year from o.created) = ?1 "
                "and trim(leading ' ' from o.status) = 'NEW'"
            )
        )

        assert _accesses(site) == [(ORDER, R)]

    def test_a_collection_member_declaration_reads_its_element_entity(self) -> None:
        # JPQL's `in(o.lines) l`, the older spelling of a join.
        site = _read(_query("select l from Order o, in(o.lines) l where o.id = ?1"))

        assert _accesses(site) == [(ORDER, R), (ORDER_LINE, R)]

    def test_a_function_in_a_from_position_names_no_table(self) -> None:
        site = _read(
            _query(
                "select o.* from orders o join lateral (select * from invoices i) x on true, "
                "generate_series(1, 3) g",
                native=True,
            )
        )

        assert _accesses(site) == [(ORDER, R), (INVOICE, R)]

    def test_a_qualified_entity_name_matches_the_class_exactly(self) -> None:
        site = _read(_query(f"select o from {ORDER} o"))

        assert _accesses(site) == [(ORDER, R)]


class TestNativeSql:
    """Rule 4: `nativeQuery = true` is SQL, and a table resolves through the
    entity's storage name."""

    def test_a_native_select_reads_the_entity_its_table_stores(self) -> None:
        site = _read(_query("select * from orders where status = ?1", native=True))

        assert _accesses(site) == [(ORDER, R)]
        assert site.accesses[0].data_model_id == data_model_id(SVC, ORDER)

    def test_a_native_insert_creates_its_target(self) -> None:
        site = _read(_query("insert into orders (id, status) values (?1, ?2)", native=True))

        assert _accesses(site) == [(ORDER, C)]

    def test_a_native_update_updates_its_target_and_reads_its_subquery(self) -> None:
        site = _read(
            _query(
                "UPDATE orders SET status = ?1 WHERE customer_id IN "
                "(SELECT id FROM customers WHERE vip)",
                native=True,
            )
        )

        assert _accesses(site) == [(ORDER, U), (CUSTOMER, R)]

    def test_a_schema_prefix_matches_the_schema_the_entity_declares(self) -> None:
        # Review B2: the qualifier is part of the name. It binds the entity
        # whose `@Table(schema=)` it names, case-folded unless quoted.
        entities = EntityCatalog(
            [
                _model(ORDER, storage_name="orders", storage_schema="public"),
                _model(INVOICE, storage_name="invoices", storage_schema="Shop"),
            ]
        )
        site = _read(
            _query("select o.* from public.orders o join shop.invoices i", native=True), entities
        )

        assert _accesses(site) == [(ORDER, R), (INVOICE, R)]
        quoted = _read(_query('select * from "Shop"."invoices"', native=True), entities)
        assert _accesses(quoted) == [(INVOICE, R)]
        miscased = _read(_query('select * from "shop".invoices', native=True), entities)
        assert _accesses(miscased) == [(None, R)]

    def test_another_schema_leaves_the_entity_undetermined_and_keeps_the_verb(self) -> None:
        entities = EntityCatalog([_model(ORDER, storage_name="orders", storage_schema="shop")])

        archived = _read(
            _query("delete from archive.orders where created < ?1", native=True), entities
        )
        assert _accesses(archived) == [(None, D)]
        assert archived.entity_type_text == "archive.orders"
        copied = _read(
            _query(
                "insert into audit.orders select * from public.orders where id = ?1", native=True
            ),
            entities,
        )
        assert _accesses(copied) == [(None, C), (None, R)]
        assert copied.entity_type_text == "audit.orders, public.orders"

    def test_a_schema_on_an_entity_that_declares_none_is_undetermined(self) -> None:
        # `public` may well be the default schema, but the entity does not say
        # it lives there, and a reader that assumed so would bind
        # `audit.orders` the same way.
        for text in ("update shop.orders set status = 'X'", 'select * from "shop"."orders"'):
            assert _accesses(_read(_query(text, native=True)))[0][0] is None, text

    def test_an_unqualified_name_binds_only_an_entity_that_declares_no_schema(self) -> None:
        # The search path decides where an unqualified name goes, and the
        # source does not state it (F1 finding 1). `orders` is the entity in
        # the default schema, never the one that declared `audit`.
        audited = f"{SHOP}.AuditedOrder"
        both = EntityCatalog(
            [
                _model(ORDER, storage_name="orders"),
                _model(audited, storage_name="orders", storage_schema="audit"),
            ]
        )
        assert _accesses(_read(_query("select * from orders", native=True), both)) == [(ORDER, R)]
        assert _accesses(_read(_query("select * from audit.orders", native=True), both)) == [
            (audited, R)
        ]
        only_audit = EntityCatalog([_model(audited, storage_name="orders", storage_schema="audit")])
        assert _accesses(_read(_query("select * from orders", native=True), only_audit)) == [
            (None, R)
        ]

    def test_a_three_part_name_is_undetermined(self) -> None:
        entities = EntityCatalog([_model(ORDER, storage_name="orders", storage_schema="shop")])
        site = _read(_query("select * from sales.shop.orders", native=True), entities)

        assert _accesses(site) == [(None, R)]

    def test_one_table_name_in_two_schemas_binds_by_its_qualifier(self) -> None:
        audit_order = f"{SHOP}.audit.Order"
        entities = EntityCatalog(
            [
                _model(ORDER, storage_name="orders", storage_schema="shop"),
                _model(audit_order, storage_name="orders", storage_schema="audit"),
            ]
        )

        assert _accesses(_read(_query("select * from audit.orders", native=True), entities)) == [
            (audit_order, R)
        ]
        # Unqualified, two entities answer to it: not resolved by picking one.
        assert _accesses(_read(_query("select * from orders", native=True), entities)) == [
            (None, R)
        ]

    def test_an_unquoted_table_name_folds_case(self) -> None:
        site = _read(_query("SELECT * FROM ORDERS", native=True))

        assert _accesses(site) == [(ORDER, R)]

    def test_a_quoted_identifier_keeps_its_case(self) -> None:
        assert _accesses(_read(_query('select * from "orders"', native=True))) == [(ORDER, R)]
        site = _read(_query('select * from "Orders"', native=True))
        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == '"Orders"'

    @pytest.mark.parametrize(
        ("text", "verb"),
        [
            ("insert ignore into orders (id) values (?1)", C),
            ("INSERT LOW_PRIORITY INTO orders (id) values (?1)", C),
            ("insert delayed into orders (id) values (?1)", C),
            ("insert high_priority ignore into orders (id) values (?1)", C),
            ("update low_priority ignore orders set status = 'X'", U),
            ("update only orders set status = 'X'", U),
            ("delete low_priority quick ignore from orders where id = ?1", D),
            ("delete from only orders where id = ?1", D),
            ("select * from only orders o join only customers c on c.id = o.customer_id", R),
        ],
    )
    def test_a_modifier_before_the_target_is_not_its_name(
        self, text: str, verb: EntityOperation
    ) -> None:
        # Review B6: MySQL's `ignore`, `low_priority`, `delayed`,
        # `high_priority` (and delete's `quick`), PostgreSQL's `only`. On the
        # base reader each became the target, with its word as the evidence.
        site = _read(_query(text, native=True))

        assert _accesses(site)[0] == (ORDER, verb)
        assert site.entity_type_text is None

    def test_sql_does_not_resolve_an_entity_name(self) -> None:
        # OrderLine stores in a table no annotation names: SQL cannot reach it
        # by its class name, and the reader does not guess a naming strategy.
        site = _read(_query("select * from OrderLine", native=True))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "OrderLine"


class TestWhatIsNotRead:
    """Rule 1 and rule 2: a query the reader does not read keeps the pre-M6
    answer, one `unknown` access on the repository's own entity."""

    def test_a_mongo_query_is_json_and_is_never_read_as_jpql(self) -> None:
        # R1-24: selection is by the repository's store, not by the text.
        for text in ("{ 'status': ?0 }", "delete from Order o"):
            site = _read(_query(text, kind=RepositoryKind.MONGO))
            assert _accesses(site) == [(ORDER, UNK)], text

    def test_a_query_with_no_text_stays_unknown_on_the_repository_entity(self) -> None:
        # Unreadable, or a named query whose name did not resolve.
        assert _accesses(_read(_query(None))) == [(ORDER, UNK)]
        unbound = _read(_query(None, entity=None))
        assert _accesses(unbound) == [(None, UNK)]
        assert unbound.entity_type_text == "E"

    def test_a_verb_outside_the_four_is_not_followed(self) -> None:
        for text in (
            "merge into orders o using customers c on (o.customer_id = c.id) "
            "when matched then update set status = 'VIP'",
            "with recent as (select * from orders) select * from recent",
            "{call archive_orders(?1)}",
            # HQL's select without `select`: not one of the four verbs.
            "from Order o where o.status = ?1",
        ):
            assert _accesses(_read(_query(text, native=True))) == [(ORDER, UNK)], text

    def test_an_insert_that_updates_on_conflict_is_an_upsert_and_is_unknown(self) -> None:
        for text in (
            "insert into orders (id, status) values (?1, ?2) "
            "on conflict (id) do update set status = excluded.status",
            "insert into orders (id, status) values (?1, ?2) "
            "on duplicate key update status = values(status)",
        ):
            assert _accesses(_read(_query(text, native=True))) == [(ORDER, UNK)], text

    @pytest.mark.parametrize(
        "text",
        [
            "select archive_orders(?1)",
            "SELECT archive_orders(?1), (select count(*) from orders)",
            "select archive_orders(?1) from dual",
            "SELECT next_order_id() FROM DUAL",
            "select * from archive_orders(?1)",
            "select * into orders_backup from orders",
        ],
    )
    def test_a_native_select_that_reads_no_table_is_not_read(self, text: str) -> None:
        # Review B2: a select with no from, or `from dual`, or only a function
        # in its from, is calling a function, and the function may write.
        # `select ... into` writes the table it names.
        assert _accesses(_read(_query(text, native=True))) == [(ORDER, UNK)]

    def test_a_native_select_from_a_table_or_a_derived_table_is_read(self) -> None:
        for text in (
            "select count(*) from orders",
            "select * from (select * from orders where status = ?1) recent",
        ):
            assert _accesses(_read(_query(text, native=True))) == [(ORDER, R)], text

    def test_a_parenthesized_select_is_the_statement_not_a_subquery(self) -> None:
        site = _read(_query("(select * from orders) union (select * from invoices)", native=True))

        assert _accesses(site) == [(ORDER, R), (INVOICE, R)]

    def test_an_insert_that_does_nothing_on_conflict_still_creates(self) -> None:
        text = "insert into orders (id) values (?1) on conflict do nothing"

        assert _accesses(_read(_query(text, native=True))) == [(ORDER, C)]


class TestTextThatIsNotStatement:
    """Rule 2: the verb and the names come from the statement, after comments
    and string literals are stripped."""

    def test_a_string_literal_names_nothing(self) -> None:
        site = _read(_query("select o from Order o where o.note = 'delete from Invoice'"))

        assert _accesses(site) == [(ORDER, R)]

    def test_a_doubled_quote_does_not_end_the_literal(self) -> None:
        site = _read(_query("select o from Order o where o.note = 'it''s from Invoice'"))

        assert _accesses(site) == [(ORDER, R)]

    def test_a_comment_is_neither_verb_nor_name(self) -> None:
        for text in (
            "/* delete stale rows */ select o from Order o",
            "-- update the status\nselect o from Order o -- from Invoice",
        ):
            assert _accesses(_read(_query(text, native=False))) == [(ORDER, R)], text

    @pytest.mark.parametrize(
        "text",
        [
            # A MySQL `#` comment.
            "select * from orders # delete from invoices\n where id = ?1",
            # A backslash-escaped quote.
            "select * from orders where note = 'it\\'s from invoices' and id = ?1",
            # PostgreSQL dollar-quoted strings.
            "select * from orders where note = $$ from invoices $$",
            "select * from orders where note = $note$ from invoices $note$",
            # A nested comment (PostgreSQL nests them; MySQL does not).
            "select * from orders /* a /* b */ join invoices */",
            # A second statement.
            "delete from order_lines where order_id = ?1; delete from orders where id = ?1",
        ],
    )
    def test_text_holding_a_construct_the_lexer_does_not_model_is_not_read(self, text: str) -> None:
        # Review B2: each of these hides text from a lexer that does not know
        # it, and the hidden part then reads as statement (a phantom Invoice
        # read on the base reader). Not read, so the site stays unknown.
        assert _accesses(_read(_query(text, native=True))) == [(ORDER, UNK)]

    def test_a_backslash_in_a_jpql_literal_is_not_read_either(self) -> None:
        text = "select o from Order o where o.note = 'it\\'s from Invoice'"

        assert _accesses(_read(_query(text))) == [(ORDER, UNK)]

    def test_what_the_lexer_does_model_is_still_read(self) -> None:
        for text in (
            "select * from orders;",
            "select * from orders ; -- done",
            "select o.total$ from orders o where o.id = ?1",
            "select * from orders where id = ?#{[0]} and owner = :#{principal.id}",
        ):
            assert _accesses(_read(_query(text, native=True))) == [(ORDER, R)], text

    def test_a_named_parameter_is_not_a_keyword(self) -> None:
        site = _read(_query("select o from Order o where o.created between :from and :to"))

        assert _accesses(site) == [(ORDER, R)]


class TestSpel:
    """`#{#entityName}` is Spring Data's name for the repository's entity."""

    def test_entity_name_resolves_to_the_repository_entity(self) -> None:
        site = _read(_query("select e from #{#entityName} e where e.status = ?1"))

        assert _accesses(site) == [(ORDER, R)]
        assert site.accesses[0].data_model_id == data_model_id(SVC, ORDER)

    def test_entity_name_in_a_native_delete(self) -> None:
        site = _read(_query("delete from #{ #entityName } where id = ?1", native=True))

        assert _accesses(site) == [(ORDER, D)]

    def test_entity_name_on_an_unbound_repository_is_undetermined(self) -> None:
        site = _read(_query("select e from #{#entityName} e", entity=None))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "E"

    @pytest.mark.parametrize(
        ("text", "written", "verb"),
        [
            ("delete from #{#entityName}_archive where id = ?1", "#{#entityName}_archive", D),
            ("select * from archive_#{#entityName}", "archive_#{#entityName}", R),
            ("insert into #{#entityName}2 (id) values (?1)", "#{#entityName}2", C),
        ],
    )
    def test_spel_joined_to_a_name_is_another_table_and_is_undetermined(
        self, text: str, written: str, verb: EntityOperation
    ) -> None:
        # Review B2: `#{#entityName}_archive` is the archive table, not the
        # entity's; the verb stays, on an entity nobody determined.
        site = _read(_query(text, native=True))

        assert _accesses(site) == [(None, verb)]
        assert site.entity_type_text == written

    def test_other_spel_in_a_name_position_is_an_undetermined_entity(self) -> None:
        site = _read(_query("select e from #{#root.domain} e where e.id = ?1"))

        assert _accesses(site) == [(None, R)]
        assert site.entity_type_text == "#{#root.domain}"

    def test_a_write_to_a_spel_target_keeps_its_verb_beside_what_it_reads(self) -> None:
        site = _read(
            _query(
                "delete from #{#root.table} where id in (select order_id from orders)",
                native=True,
            )
        )

        assert _accesses(site) == [(None, D), (ORDER, R)]

    def test_spel_in_a_parameter_is_not_a_name(self) -> None:
        site = _read(_query("select o from Order o where o.owner = :#{principal.from}"))

        assert _accesses(site) == [(ORDER, R)]


class TestJpqlJoins:
    """A join target resolves through the alias's entity and the field's
    declared type, generic element type included (rule 3)."""

    def test_a_join_over_a_collection_reads_its_element_entity(self) -> None:
        # `lines` is `List<OrderLine>`: the erased type says java.util.List,
        # and only the declared type names the entity the join reaches.
        site = _read(_query("select o from Order o join o.lines l where l.sku = ?1"))

        assert _accesses(site) == [(ORDER, R), (ORDER_LINE, R)]

    def test_join_fetch_reads_the_join_target_and_fetch_is_no_entity(self) -> None:
        site = _read(_query("select distinct o from Order o left join fetch o.lines"))

        assert _accesses(site) == [(ORDER, R), (ORDER_LINE, R)]

    def test_a_to_one_join_resolves_through_the_field_type(self) -> None:
        site = _read(_query("select o from Order o inner join o.customer c where c.vip = true"))

        assert _accesses(site) == [(ORDER, R), (CUSTOMER, R)]

    def test_a_path_in_a_subquery_from_resolves_through_the_outer_alias(self) -> None:
        site = _read(
            _query("select o from Order o where exists (select l from o.lines l where l.qty > 1)")
        )

        assert _accesses(site) == [(ORDER, R), (ORDER_LINE, R)]

    @pytest.mark.parametrize(
        "text",
        [
            "select o from Order o join o.tags t where t = ?1",
            "select o from Order o join o.items i where i.sku = ?1",
            "select o from Order o, in(o.tags) t",
            "select o from Order o left join o.address a",
            "select o from Order o join o.notes n",
        ],
    )
    def test_a_join_over_a_path_to_a_non_entity_adds_no_access(self, text: str) -> None:
        # Review B6: an @ElementCollection of strings, a list of embeddables,
        # an embedded value. The base reader added an undetermined read for
        # each, so the site counted as entity_undetermined.
        site = _read(_query(text), ELEMENTS)

        assert _accesses(site) == [(ORDER, R)]
        assert site.entity_type_text is None

    def test_a_path_whose_type_cannot_be_resolved_stays_undetermined(self) -> None:
        for text in (
            # A raw collection, and a wildcard: the element type is not written.
            "select o from Order o join o.raw r",
            "select o from Order o join o.qualified_raw r",
            "select o from Order o join o.wild w",
            # Through a non-entity, whose fields the catalog does not hold.
            "select o from Order o join o.address.country c",
            "select o from Order o join o.items i join i.product p",
        ):
            assert _accesses(_read(_query(text), ELEMENTS)) == [(ORDER, R), (None, R)], text

    def test_an_entity_join_names_its_entity_directly(self) -> None:
        site = _read(_query("select o from Order o join Client c on c.id = o.customer.id"))

        assert _accesses(site) == [(ORDER, R), (CUSTOMER, R)]
