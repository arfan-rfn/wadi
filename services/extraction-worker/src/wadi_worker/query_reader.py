"""The query reader (milestone M6, §5.2.17): what an annotated query does.

A repository method carrying ``@Query`` or ``@Modifying``, or resolving to a
``@NamedQuery``/``@NamedNativeQuery``, is decided by its query and never by
its name (R1-12). This module reads that query by keyword and position. It is
a keyword-level reader, not a SQL or JPQL parser, so what it reads and what it
does not are both listed here.

What it reads:

* **Which reader (R1-24).** ``native`` is SQL. A query on a Mongo repository
  is JSON and is not read. Everything else is JPQL. No text (an unreadable
  annotation, or a named query whose name did not resolve) is not read.
* **The verb** is the statement's first keyword once comments are dropped and
  string literals made opaque: ``select`` reads, ``update`` updates,
  ``delete`` deletes, ``insert`` creates. Any other first word (``merge``,
  ``with``, ``call``, HQL's select that starts at ``from``) is not followed,
  and neither is an insert that updates on conflict, which is an upsert.
* **Names are declared by position**: after ``from``, after ``join`` (with
  ``fetch`` skipped), after a comma in a from clause, as the target of
  ``update``, ``delete [from]`` and ``insert into``, and in JPQL's
  ``in(o.lines)``. That holds in the statement and in every subquery. An
  entity named like a keyword (``Order``) is an entity in those positions and
  nowhere else. A ``from`` inside a function's parentheses (``extract(year
  from d)``) names nothing. SQL's statement modifiers before a name (MySQL's
  ``ignore``, ``low_priority``, ``delayed``, ``high_priority``, ``quick``,
  PostgreSQL's ``only``) are skipped, never read as one (review B6).
* **JPQL names** match the service's own entities case-sensitively, the
  ``@Entity(name=)`` value first and the simple class name second. A join over
  an association path (``o.lines l``) resolves through the field's declared
  type, the element type of a collection; a path whose type is written and is
  no entity's (an ``@ElementCollection`` of strings, an embeddable) adds no
  access (review B6). **SQL tables** match the storage name,
  case-insensitively unless quoted. A schema-qualified name binds only the
  entity whose ``@Table(schema=)`` is that qualifier (review B2), and an
  unqualified name binds only an entity that declares no schema.
  ``#{#entityName}``, written alone, is the repository's own entity.
* **One access per entity (rule 6, C1).** The verb applies to the target of a
  write statement, or to every entity a select names. Every other entity a
  write statement names is read. One entity with two operations keeps both.
  A name that resolves to nothing keeps the verb, on an undetermined entity.

What it does not read, so the site stays ``unknown`` on the repository's own
entity:

* A CTE, ``merge``, or a stored procedure call.
* A native select that reads no table of its own: no ``from``, ``from dual``,
  only a function in its from clause, or ``select ... into``. The function it
  calls may write, and ``into`` writes the table it names (review B2).
* Text holding a construct the lexer does not model: a ``#`` outside a
  literal (a MySQL comment, or a PostgreSQL operator), a backslash inside a
  literal, a dollar-quoted string, a nested comment, a MySQL executable
  comment (``/*! ... */``, whose text MySQL runs), or a second statement after
  a ``;`` (review B2). Read on regardless, the hidden part would read as
  statement.

What it reads as undetermined, keeping the verb:

* A schema qualifier the entity does not declare (``audit.orders`` for an
  entity in no schema, or in another), and any three-part name. An
  unqualified name for an entity that declares a schema (``orders`` when only
  ``audit.orders`` is mapped), because the search path is not in the source.
* SpEL in a name position other than a bare ``#{#entityName}``, including one
  joined to a name (``#{#entityName}_archive``).
* A join path whose type cannot be read: an owner or field the catalog lacks,
  a raw collection, a wildcard, or a name two entities share.

What it does not see, and therefore does not claim:

* An implicit join through a path outside a declaration: ``where
  o.customer.vip = true`` reads Customer, and only Order is claimed.
* Text it was not given: a query built at runtime, or a concatenation the
  export could not read back from the annotation (§5.2.17, M0).
* PostgreSQL's ``delete ... using``, MySQL's multi-table ``delete o, l from``
  (its targets read as reads), ``straight_join``, the subtype of a
  ``treat(...)`` join, a table-valued function beside a table, and a table
  whose name only a naming strategy derives: an entity without a storage name
  matches no table.
* A type variable as a collection's element (``List<T>``) reads as a class
  that is not an entity, so a join over it adds no access.
* Entity inheritance: a query on a superclass entity claims that entity only.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Literal, NamedTuple

from wadi_contracts import DataModel, EntityOperation
from wadi_joern_client.export import ExportDbAccess, RepositoryKind


class NotAnEntity(Enum):
    """A join path that resolved to a type no entity of the service has."""

    TYPE = "not-an-entity"


NOT_AN_ENTITY = NotAnEntity.TYPE

_CONTAINERS: frozenset[str] = frozenset(
    f"java.util.{name}"
    for name in (
        "Collection",
        "List",
        "Set",
        "SortedSet",
        "NavigableSet",
        "Queue",
        "Deque",
        "Map",
        "SortedMap",
        "NavigableMap",
        "ArrayList",
        "LinkedList",
        "HashSet",
        "LinkedHashSet",
        "TreeSet",
        "HashMap",
        "LinkedHashMap",
        "TreeMap",
    )
) | {"java.lang.Iterable"}
"""Erased collection types: their element is only in the declared type."""

_CONTAINER_NAMES: frozenset[str] = frozenset(name.rsplit(".", 1)[-1] for name in _CONTAINERS)
"""A raw collection's declared type is its own name, simple or qualified:
the element is unknown."""


class EntityCatalog:
    """One service's entity records, indexed the ways a query names them.

    Built once per export from the worker's own ``DataModel`` records, so a
    resolved name carries the same ``dm_`` id as every other access. A record
    without a qualified name (a pre-2.14.0 export) cannot be named by an
    access and is left out.
    """

    def __init__(self, models: Iterable[DataModel] = ()) -> None:
        self._models: dict[str, DataModel] = {
            model.type_full_name: model for model in models if model.type_full_name
        }

    def model_id(self, entity: str | None) -> str | None:
        """The ``dm_`` id of a qualified entity type; None when it has no record."""
        model = self._models.get(entity) if entity else None
        return model.id if model else None

    def delete_rewritten_by(self, entity: str | None) -> str | None:
        """The Hibernate annotation that replaces the entity's DELETE, if any."""
        model = self._models.get(entity) if entity else None
        return model.delete_rewritten_by if model else None

    def jpql_entity(self, name: str) -> str | None:
        """The entity a JPQL entity name denotes; None unless exactly one does.

        Case-sensitive. An entity's JPQL name is its ``@Entity(name=)`` value
        when it sets one and its simple class name otherwise, so the
        ``jpql_name`` match comes first, and a class that renamed itself no
        longer answers to its class name (JPA's own rule). A qualified name,
        which Hibernate also accepts, matches the class exactly.
        """
        if "." in name:
            return name if name in self._models else None
        by_jpql_name = _only(
            full for full, model in self._models.items() if model.jpql_name == name
        )
        if by_jpql_name is not None:
            return by_jpql_name
        return _only(
            full
            for full, model in self._models.items()
            if model.jpql_name is None and model.entity == name
        )

    def table_entity(
        self,
        name: str,
        *,
        quoted: bool,
        schema: str | None = None,
        schema_quoted: bool = False,
    ) -> str | None:
        """The entity stored in a SQL table; None unless exactly one is.

        An unquoted SQL identifier folds case, so it matches the storage name
        case-insensitively; a quoted one keeps its case and matches exactly.
        An entity without a storage name matches no table: the reader does not
        guess the naming strategy that would have derived one. A ``schema``
        qualifier is matched the same way against the entity's
        ``storage_schema``, and an entity that declares none matches no
        qualified name (review B2): ``audit.orders`` is not ``orders`` because
        both end in the same word. The rule runs the other way too: an
        unqualified name binds only an entity that declares no schema. Which
        schema an unqualified name resolves to is the connection's search
        path, which the source does not state, so ``orders`` reaches the
        entity in the default schema and never one that declared ``audit``.
        """
        return _only(
            full
            for full, model in self._models.items()
            if _same_identifier(model.storage_name, name, quoted=quoted)
            and (
                model.storage_schema is None
                if schema is None
                else _same_identifier(model.storage_schema, schema, quoted=schema_quoted)
            )
        )

    def field_target(self, owner: str | None, field_name: str) -> str | NotAnEntity | None:
        """The entity a field of ``owner`` reaches, for a join over it.

        The erased ``type_name`` is qualified and answers a to-one field. A
        collection erases to its container, so its element is read from the
        declared type (``List<OrderLine>`` is ``OrderLine``), then resolved as
        a Java type name: a qualified name exactly, a simple name only when one
        entity has it.

        :data:`NOT_AN_ENTITY` when the type is written and no entity of the
        service has it: a basic value (``Set<String>``), an embeddable, an
        embedded value (review B6). The catalog holds every entity, so a type
        it lacks is not one. None when the type cannot be read: an owner or
        field the catalog does not have, a raw collection, a wildcard, or a
        name two entities share.
        """
        model = self._models.get(owner) if owner else None
        found = next((f for f in model.fields if f.name == field_name), None) if model else None
        if found is None:
            return None
        if found.type_name in self._models:
            return found.type_name
        element = _element_type(found.declared_type)
        raw = found.type_name in _CONTAINERS and (
            element in _CONTAINERS or element in _CONTAINER_NAMES
        )
        if element is None or raw:
            return None
        if element in self._models:
            return element
        named = list(
            dict.fromkeys(full for full, model in self._models.items() if model.entity == element)
        )
        if not named:
            return NOT_AN_ENTITY
        return named[0] if len(named) == 1 else None


def _same_identifier(declared: str | None, written: str, *, quoted: bool) -> bool:
    """Whether a SQL identifier as written names ``declared``: exactly when
    quoted, case-folded otherwise. Nothing declared matches nothing."""
    if not declared:
        return False
    return declared == written if quoted else declared.lower() == written.lower()


def _element_type(declared: str | None) -> str | None:
    """The type a declared field type holds: the last type argument of a
    generic (a map's value), else the type itself, with generics stripped."""
    if not declared:
        return None
    text = declared.strip()
    if "<" in text and text.endswith(">"):
        arguments = text[text.index("<") + 1 : -1]
        depth, last = 0, 0
        for index, char in enumerate(arguments):
            depth += {"<": 1, ">": -1}.get(char, 0)
            if char == "," and depth == 0:
                last = index + 1
        text = arguments[last:].strip()
    text = text.split("<", 1)[0].removeprefix("? extends ").strip()
    # `?` and `? super X` say nothing exact about the element.
    return text if text and not text.startswith("?") else None


def _only(candidates: Iterable[str]) -> str | None:
    """The one candidate, or None when there is none or more than one: a name
    two entities answer to is not resolved by picking one (P10)."""
    found = list(dict.fromkeys(candidates))
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class QueryReading:
    """What one statement does: one (entity, operation) per access, in order of
    appearance, and the names as written that resolved to no entity."""

    accesses: tuple[tuple[str | None, EntityOperation], ...]
    unresolved: tuple[str, ...]


_VERBS: dict[str, EntityOperation] = {
    "select": EntityOperation.READ,
    "update": EntityOperation.UPDATE,
    "delete": EntityOperation.DELETE,
    "insert": EntityOperation.CREATE,
}
"""Rule 2: the statement's first keyword. Anything else is not followed."""


class _Language(StrEnum):
    JPQL = "jpql"
    SQL = "sql"


def read_repository_query(db: ExportDbAccess, entities: EntityCatalog) -> QueryReading | None:
    """Read the query one repository call carries; None when it is not read.

    Selection (R1-24): ``native`` (``nativeQuery = true`` or a
    ``@NamedNativeQuery``) is SQL; a query on a Mongo repository is JSON,
    which this reader does not read; everything else is JPQL. No text (an
    unreadable annotation, or a named query whose name did not resolve) is
    not read either.
    """
    query = db.query
    if query is None or query.text is None:
        return None
    if query.native:
        language = _Language.SQL
    elif db.repository_kind is RepositoryKind.MONGO:
        return None
    else:
        language = _Language.JPQL
    try:
        return _Statement(
            _tokenize(query.text),
            language,
            entities,
            repository_entity=db.entity_type_full_name,
            # The evidence when the repository's entity did not bind (R1-4).
            repository_entity_text=db.entity_type_text or _ENTITY_NAME_SPEL,
        ).read()
    except _UnmodeledTextError:
        return None


_ENTITY_NAME_SPEL = "#{#entityName}"
"""Spring Data's SpEL for the repository's own entity, written without spaces."""


class _Segment(NamedTuple):
    text: str
    """Without its quotes."""
    quoted: bool


@dataclass(frozen=True)
class _Token:
    """One lexical token, with its source text. A name keeps its dotted
    segments (``o.lines``, ``public."Orders"``). A literal (a string or a
    number) and a parameter (``?1``, ``:status``, ``:#{...}``) are never a
    keyword or a name; ``spel`` is a bare ``#{...}`` expression."""

    kind: Literal["name", "spel", "param", "literal", "other"]
    text: str
    start: int
    """Offset in the query text: two tokens with no space between them are
    one name to SQL (``#{#entityName}_archive``)."""
    segments: tuple[_Segment, ...] = ()

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    @property
    def name_like(self) -> bool:
        """A piece a name can be glued together from."""
        return (
            self.kind in ("name", "spel")
            or (self.kind == "literal" and self.text[:1].isdigit())
            or self.text == "."
        )

    @property
    def keyword(self) -> str | None:
        """The lower-cased word, for a single unquoted segment: keywords are
        case-insensitive, and neither a dotted nor a quoted name is one."""
        if self.kind != "name" or len(self.segments) != 1 or self.segments[0].quoted:
            return None
        return self.text.lower()


_QUOTES = {'"': '"', "`": "`"}
"""SQL's quoted identifier and MySQL's."""


class _UnmodeledTextError(Exception):
    """The text holds a construct this reader does not model (review B2).

    Each one hides text from a lexer that does not know it: a MySQL ``#``
    comment or executable comment, a backslash-escaped quote, a PostgreSQL
    dollar-quoted string or nested comment, or a second statement. Read on
    regardless, the hidden part becomes statement, so the query is not read
    at all.
    """


_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
"""PostgreSQL's ``$$`` or ``$tag$`` opening a dollar-quoted string."""


def _tokenize(text: str) -> list[_Token]:
    """The statement's tokens, with comments dropped and literals opaque.

    Raises :class:`_UnmodeledTextError` for text it cannot split reliably.
    """
    tokens: list[_Token] = []
    i = 0
    while i < len(text):
        char, pair = text[i], text[i : i + 2]
        start = i
        if char.isspace():
            i += 1
            continue
        if pair == "--":
            i = _end_of(text, "\n", i + 2)
            continue
        if pair == "/*":
            if text[i + 2 : i + 3] == "!":
                # MySQL runs what an executable comment holds (§5.2.17).
                raise _UnmodeledTextError("a MySQL executable comment")
            i = _end_of(text, "*/", i + 2)
            if "/*" in text[start + 2 : i]:
                raise _UnmodeledTextError("a nested comment")
            continue
        if char == "#" and pair != "#{":
            raise _UnmodeledTextError("a # outside a literal")
        if char == "$" and _DOLLAR_QUOTE.match(text, i):
            raise _UnmodeledTextError("a dollar-quoted string")
        if tokens and tokens[-1].text == ";":
            raise _UnmodeledTextError("a second statement")
        if char == "'":
            i = _end_of_literal(text, i + 1)
            if "\\" in text[start:i]:
                raise _UnmodeledTextError("a backslash inside a literal")
            tokens.append(_Token("literal", text[start:i], start))
        elif pair == "#{":
            i = _end_of_spel(text, i + 1)
            tokens.append(_Token("spel", text[start:i], start))
        elif char in "?:" and text[i + 1 : i + 3] == "#{":
            i = _end_of_spel(text, i + 2)
            tokens.append(_Token("param", text[start:i], start))
        elif char == "?" or (char == ":" and i + 1 < len(text) and _starts_word(text[i + 1])):
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(_Token("param", text[start:i], start))
        elif char.isdigit():
            while i < len(text) and (text[i].isalnum() or text[i] == "."):
                i += 1
            tokens.append(_Token("literal", text[start:i], start))
        elif _starts_word(char) or char in _QUOTES:
            segments: list[_Segment] = []
            while True:
                segment, i = _segment(text, i)
                segments.append(segment)
                if (
                    i + 1 < len(text)
                    and text[i] == "."
                    and (_starts_word(text[i + 1]) or text[i + 1] in _QUOTES)
                ):
                    i += 1
                    continue
                break
            tokens.append(_Token("name", text[start:i], start, tuple(segments)))
        else:
            i += 2 if pair == "::" else 1
            tokens.append(_Token("other", text[start:i], start))
    return tokens


def _end_of(text: str, terminator: str, i: int) -> int:
    """Past the next ``terminator``, or the end of the text when there is none."""
    found = text.find(terminator, i)
    return len(text) if found < 0 else found + len(terminator)


def _end_of_literal(text: str, i: int) -> int:
    """Past the quote closing a string literal; a doubled quote is one quote."""
    while i < len(text):
        if text[i] == "'" and text[i + 1 : i + 2] == "'":
            i += 2
        elif text[i] == "'":
            return i + 1
        else:
            i += 1
    return i


def _end_of_spel(text: str, i: int) -> int:
    """Past the brace closing the SpEL expression whose ``{`` is at ``i``."""
    depth = 0
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return i
    return i


def _segment(text: str, i: int) -> tuple[_Segment, int]:
    """One name segment at ``i``: a word, or a quoted identifier (a doubled
    quote inside it is one quote character)."""
    close = _QUOTES.get(text[i])
    if close is None:
        start = i
        while i < len(text) and (text[i].isalnum() or text[i] in "_$"):
            i += 1
        return _Segment(text[start:i], quoted=False), i
    i += 1
    chars: list[str] = []
    while i < len(text):
        if text[i] == close and text[i + 1 : i + 2] == close:
            chars.append(close)
            i += 2
        elif text[i] == close:
            i += 1
            break
        else:
            chars.append(text[i])
            i += 1
    return _Segment("".join(chars), quoted=True), i


def _starts_word(char: str) -> bool:
    return char.isalpha() or char in "_$"


class _Mention(NamedTuple):
    entity: str | None
    written: str
    target: bool


@dataclass
class _Frame:
    """One parenthesis level. A query frame (a subquery, or the statement)
    holds declarations; any other parenthesis is an expression, so a ``from``
    inside it (``extract(year from d)``) names nothing."""

    query: bool
    aliases: dict[str, str | None] = field(default_factory=dict[str, str | None])
    """Identification variable (lower-cased: JPQL's are case-insensitive) to
    the entity it ranges over, None when that entity did not resolve."""
    in_from: bool = False
    """Inside this frame's from clause, where a comma starts a declaration."""


class _Statement:
    """One pass over a statement's tokens, collecting its declarations."""

    def __init__(
        self,
        tokens: Sequence[_Token],
        language: _Language,
        entities: EntityCatalog,
        *,
        repository_entity: str | None,
        repository_entity_text: str,
    ) -> None:
        self._tokens = tokens
        self._language = language
        self._entities = entities
        self._repository_entity = repository_entity
        self._repository_entity_text = repository_entity_text
        self._mentions: list[_Mention] = []
        self._frames = [_Frame(query=True)]
        # What the statement's own from clause declares, for a native select
        # that may only be calling a function (review B2).
        self._top_depth = 1
        self._top_from = False
        self._top_tables: list[str] = []
        self._top_derived = False
        self._top_into = False

    def read(self) -> QueryReading | None:
        first = next((i for i, t in enumerate(self._tokens) if t.text != "("), None)
        verb = _VERBS.get(self._keyword(first) or "") if first is not None else None
        if first is None or verb is None or self._is_upsert(verb):
            return None
        frames = self._frames
        # `(select ...) union (select ...)`: the leading parentheses hold the
        # statement itself, so their frames are its top level.
        self._top_depth = first + 1
        i = 0
        while i < len(self._tokens):
            if i == first:
                i = self._head(i, verb)
                continue
            token = self._tokens[i]
            if token.text == "(":
                frames.append(_Frame(query=self._keyword(i + 1) == "select"))
            elif token.text == ")":
                if len(frames) > 1:
                    frames.pop()
            elif frames[-1].query and (
                token.keyword == "from" or (token.text == "," and frames[-1].in_from)
            ):
                frames[-1].in_from = True
                self._top_from = self._top_from or self._at_top()
                i = self._declaration(i + 1, target=False)
                continue
            elif frames[-1].query and token.keyword == "join":
                # `join fetch` loads the target eagerly: `fetch` is never an entity.
                i += 2 if self._keyword(i + 1) == "fetch" else 1
                i = self._declaration(i, target=False)
                continue
            elif token.keyword in _CLAUSES:
                frames[-1].in_from = False
            elif token.keyword == "into" and self._at_top():
                self._top_into = True
            i += 1
        if self._language is _Language.SQL and verb is EntityOperation.READ and self._calls_only():
            return None
        accesses = tuple(
            dict.fromkeys(
                (m.entity, verb if m.target else EntityOperation.READ) for m in self._mentions
            )
        )
        unresolved = tuple(dict.fromkeys(m.written for m in self._mentions if m.entity is None))
        # A statement whose entity the reader found no name for still has its
        # verb: it keeps it, on an undetermined entity (rule 6).
        return QueryReading(accesses=accesses or ((None, verb),), unresolved=unresolved)

    def _at_top(self) -> bool:
        """Whether the current frame is the statement's own, not a subquery's."""
        return len(self._frames) <= self._top_depth

    def _calls_only(self) -> bool:
        """Whether a native select reads no table of its own: no from, only
        ``dual`` or a function there, or ``select ... into``, which writes.
        A function a select calls may write, and nothing here reads its body.
        A derived table (``from (select ...) x``) is read like any subquery."""
        if self._top_into or not self._top_from:
            return True
        tables = [name for name in self._top_tables if name.lower() != "dual"]
        return not tables and not self._top_derived

    def _head(self, i: int, verb: EntityOperation) -> int:
        """Past the first keyword; a write statement's target is declared here."""
        if verb is EntityOperation.READ:
            return i + 1
        i = self._past_modifiers(i + 1)
        if self._keyword(i) in ("from", "into"):
            i += 1
        return self._declaration(i, target=True)

    def _past_modifiers(self, i: int) -> int:
        """Past SQL's statement modifiers, which are never a name (review B6)."""
        while self._language is _Language.SQL and self._keyword(i) in _SQL_MODIFIERS:
            i += 1
        return i

    def _declaration(self, i: int, *, target: bool) -> int:
        """One entity declaration at ``i``: its name and optional alias."""
        i = self._past_modifiers(i)
        if i >= len(self._tokens):
            return i
        name = self._tokens[i]
        called = i + 1 < len(self._tokens) and self._tokens[i + 1].text == "("
        glued = self._glued_name(i)
        if any(token.kind == "spel" for token in glued):
            # Only a bare `#{#entityName}` is the repository's entity. Any
            # other SpEL, or one joined to a name (`#{#entityName}_archive`),
            # names a table nothing here can evaluate (review B2).
            if len(glued) == 1 and "".join(name.text.split()) == _ENTITY_NAME_SPEL:
                entity, written = self._repository_entity, self._repository_entity_text
            else:
                entity, written = None, "".join(token.text for token in glued)
            i += len(glued) - 1
        elif (
            self._language is _Language.JPQL
            and name.keyword == "in"
            and called
            and i + 3 < len(self._tokens)
            and self._tokens[i + 3].text == ")"
        ):
            # JPQL's collection member declaration, `in(o.lines) l`: a join.
            i += 2
            name = self._tokens[i]
            if name.kind != "name":
                # `in(:ids) x` declares nothing a path names; reading on
                # would guess (pre-landing review #3).
                raise _UnmodeledTextError("a collection member declaration over a non-path")
            entity, written = self._resolve(name), name.text
            i += 1
        elif name.kind == "name" and (target or not called):
            entity, written = self._resolve(name), name.text
        else:
            # A function (`treat(...)`, `generate_series(...)`), `lateral`, or
            # a derived table: the main loop reads any subquery inside it. A
            # write target followed by `(` is its column list, not a call.
            if self._at_top() and (name.text == "(" or name.keyword == "lateral"):
                self._top_derived = True
            return i
        if self._at_top():
            self._top_tables.append(written)
        # A join over a path to a value or an embeddable touches no entity
        # (review B6); its alias still ranges over something, unresolved.
        if entity is not NOT_AN_ENTITY:
            self._mentions.append(_Mention(entity, written, target))
        i += 1
        if self._keyword(i) == "as":
            i += 1
        alias = self._keyword(i)
        if alias is not None and alias not in _NOT_AN_ALIAS:
            self._frames[-1].aliases[alias] = entity if isinstance(entity, str) else None
            i += 1
        return i

    def _glued_name(self, i: int) -> list[_Token]:
        """The token at ``i`` and every name piece written against it."""
        run = [self._tokens[i]]
        for token in self._tokens[i + 1 :]:
            if token.start != run[-1].end or not token.name_like:
                break
            run.append(token)
        return run

    def _resolve(self, name: _Token) -> str | NotAnEntity | None:
        """An entity name, or a path over an alias in scope (``o.lines``); in
        SQL a table name, whose schema qualifier must be the one the entity
        declares (``shop.orders``). A catalog qualifier (``db.shop.orders``)
        is never declared, so a three-part name resolves to nothing."""
        if self._language is _Language.SQL:
            *qualifiers, table = name.segments
            if len(qualifiers) > 1:
                return None
            schema = qualifiers[0] if qualifiers else None
            return self._entities.table_entity(
                table.text,
                quoted=table.quoted,
                schema=schema.text if schema else None,
                schema_quoted=schema.quoted if schema else False,
            )
        head, *path = (segment.text for segment in name.segments)
        if not path:
            return self._entities.jpql_entity(head)
        scope = next((f.aliases for f in reversed(self._frames) if head.lower() in f.aliases), None)
        if scope is None:
            return self._entities.jpql_entity(name.text)
        entity: str | NotAnEntity | None = scope[head.lower()]
        for field_name in path:
            # Past a non-entity the catalog holds no fields: unresolved.
            entity = (
                self._entities.field_target(entity, field_name) if isinstance(entity, str) else None
            )
        return entity

    def _is_upsert(self, verb: EntityOperation) -> bool:
        """An insert that updates on conflict (PostgreSQL's ``on conflict ...
        do update``, MySQL's ``on duplicate key update``) is an upsert: it may
        create or update, and no one of the four verbs says which (rule 2)."""
        if verb is not EntityOperation.CREATE:
            return False
        words = f" {' '.join(token.keyword or '?' for token in self._tokens)} "
        return " on duplicate key update " in words or (
            " on conflict " in words and " do update " in words
        )

    def _keyword(self, i: int | None) -> str | None:
        if i is None or i >= len(self._tokens):
            return None
        return self._tokens[i].keyword


_CLAUSES: frozenset[str] = frozenset(
    {
        "where",
        "group",
        "order",
        "having",
        "union",
        "intersect",
        "except",
        "set",
        "limit",
        "offset",
        "fetch",
        "for",
        "returning",
        "window",
        "values",
        "select",
    }
)
"""Words that end a from clause: a comma after one is not a declaration."""

_SQL_MODIFIERS: frozenset[str] = frozenset(
    {"ignore", "low_priority", "delayed", "high_priority", "quick", "only"}
)
"""Words SQL writes between a verb (or ``from``) and the table: MySQL's
insert/update/delete modifiers and PostgreSQL's ``only`` (no inheritance
children). Skipped in SQL only, because JPQL has none of them and an entity
may be named ``Only``."""

_NOT_AN_ALIAS: frozenset[str] = _CLAUSES | {
    "from",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "cross",
    "full",
    "natural",
    "on",
    "using",
    "with",
}
"""Words that follow a declaration and are never its alias."""
