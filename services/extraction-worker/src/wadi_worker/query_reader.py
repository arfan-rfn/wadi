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
  from d)``) names nothing.
* **JPQL names** match the service's own entities case-sensitively, the
  ``@Entity(name=)`` value first and the simple class name second. A join over
  an association path (``o.lines l``) resolves through the field's declared
  type, the element type of a collection. **SQL tables** match the storage
  name, case-insensitively unless quoted, on the last segment of a
  schema-qualified name. ``#{#entityName}`` is the repository's own entity.
* **One access per entity (rule 6, C1).** The verb applies to the target of a
  write statement, or to every entity a select names. Every other entity a
  write statement names is read. One entity with two operations keeps both.
  A name that resolves to nothing keeps the verb, on an undetermined entity.

What it does not see, and therefore does not claim:

* An implicit join through a path outside a declaration: ``where
  o.customer.vip = true`` reads Customer, and only Order is claimed.
* A CTE, ``merge``, or a stored procedure call: not followed, so the site
  stays ``unknown`` on the repository's entity.
* SpEL other than ``#{#entityName}`` in a name position: undetermined.
* Text it was not given: a query built at runtime, or a concatenation the
  export could not read back from the annotation (§5.2.17, M0).
* PostgreSQL's ``delete ... using``, the subtype of a ``treat(...)`` join, a
  table-valued function, dollar-quoted strings, and a table whose name only a
  naming strategy derives: an entity without a storage name matches no table.
* Entity inheritance: a query on a superclass entity claims that entity only.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, NamedTuple

from wadi_contracts import DataModel, EntityOperation
from wadi_joern_client.export import ExportDbAccess, RepositoryKind


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

    def table_entity(self, name: str, *, quoted: bool) -> str | None:
        """The entity stored in a SQL table; None unless exactly one is.

        An unquoted SQL identifier folds case, so it matches the storage name
        case-insensitively; a quoted one keeps its case and matches exactly.
        An entity without a storage name matches no table: the reader does not
        guess the naming strategy that would have derived one.
        """
        folded = name if quoted else name.lower()
        return _only(
            full
            for full, model in self._models.items()
            if model.storage_name
            and (model.storage_name if quoted else model.storage_name.lower()) == folded
        )

    def field_target(self, owner: str | None, field_name: str) -> str | None:
        """The entity a field of ``owner`` reaches, for a join over it.

        The erased ``type_name`` is qualified and answers a to-one field. A
        collection erases to its container, so its element is read from the
        declared type (``List<OrderLine>`` is ``OrderLine``), then resolved as
        a Java type name: a qualified name exactly, a simple name only when one
        entity has it.
        """
        model = self._models.get(owner) if owner else None
        found = next((f for f in model.fields if f.name == field_name), None) if model else None
        if found is None:
            return None
        if found.type_name in self._models:
            return found.type_name
        element = _element_type(found.declared_type)
        if element is None:
            return None
        if element in self._models:
            return element
        return _only(full for full, model in self._models.items() if model.entity == element)


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
    return text or None


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
    return _Statement(
        _tokenize(query.text),
        language,
        entities,
        repository_entity=db.entity_type_full_name,
        # The evidence when the repository's entity did not bind (R1-4).
        repository_entity_text=db.entity_type_text or _ENTITY_NAME_SPEL,
    ).read()


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
    segments: tuple[_Segment, ...] = ()

    @property
    def keyword(self) -> str | None:
        """The lower-cased word, for a single unquoted segment: keywords are
        case-insensitive, and neither a dotted nor a quoted name is one."""
        if self.kind != "name" or len(self.segments) != 1 or self.segments[0].quoted:
            return None
        return self.text.lower()


_QUOTES = {'"': '"', "`": "`"}
"""SQL's quoted identifier and MySQL's."""


def _tokenize(text: str) -> list[_Token]:
    """The statement's tokens, with comments dropped and literals opaque."""
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
            i = _end_of(text, "*/", i + 2)
            continue
        if char == "'":
            i = _end_of_literal(text, i + 1)
            tokens.append(_Token("literal", text[start:i]))
        elif pair == "#{":
            i = _end_of_spel(text, i + 1)
            tokens.append(_Token("spel", text[start:i]))
        elif char in "?:" and text[i + 1 : i + 3] == "#{":
            i = _end_of_spel(text, i + 2)
            tokens.append(_Token("param", text[start:i]))
        elif char == "?" or (char == ":" and i + 1 < len(text) and _starts_word(text[i + 1])):
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(_Token("param", text[start:i]))
        elif char.isdigit():
            while i < len(text) and (text[i].isalnum() or text[i] == "."):
                i += 1
            tokens.append(_Token("literal", text[start:i]))
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
            tokens.append(_Token("name", text[start:i], tuple(segments)))
        else:
            i += 2 if pair == "::" else 1
            tokens.append(_Token("other", text[start:i]))
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

    def read(self) -> QueryReading | None:
        first = next((i for i, t in enumerate(self._tokens) if t.text != "("), None)
        verb = _VERBS.get(self._keyword(first) or "") if first is not None else None
        if first is None or verb is None or self._is_upsert(verb):
            return None
        frames = self._frames
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
                i = self._declaration(i + 1, target=False)
                continue
            elif frames[-1].query and token.keyword == "join":
                # `join fetch` loads the target eagerly: `fetch` is never an entity.
                i += 2 if self._keyword(i + 1) == "fetch" else 1
                i = self._declaration(i, target=False)
                continue
            elif token.keyword in _CLAUSES:
                frames[-1].in_from = False
            i += 1
        accesses = tuple(
            dict.fromkeys(
                (m.entity, verb if m.target else EntityOperation.READ) for m in self._mentions
            )
        )
        unresolved = tuple(dict.fromkeys(m.written for m in self._mentions if m.entity is None))
        # A statement whose entity the reader found no name for still has its
        # verb: it keeps it, on an undetermined entity (rule 6).
        return QueryReading(accesses=accesses or ((None, verb),), unresolved=unresolved)

    def _head(self, i: int, verb: EntityOperation) -> int:
        """Past the first keyword; a write statement's target is declared here."""
        if verb is EntityOperation.READ:
            return i + 1
        i += 1
        if self._keyword(i) in ("from", "into"):
            i += 1
        return self._declaration(i, target=True)

    def _declaration(self, i: int, *, target: bool) -> int:
        """One entity declaration at ``i``: its name and optional alias."""
        if i >= len(self._tokens):
            return i
        name = self._tokens[i]
        called = i + 1 < len(self._tokens) and self._tokens[i + 1].text == "("
        if name.kind == "spel" and "".join(name.text.split()) == _ENTITY_NAME_SPEL:
            entity, written = self._repository_entity, self._repository_entity_text
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
            entity, written = self._resolve(name), name.text
            i += 1
        elif name.kind == "name" and (target or not called):
            entity, written = self._resolve(name), name.text
        else:
            # A function (`treat(...)`, `generate_series(...)`), `lateral`, or
            # a derived table: the main loop reads any subquery inside it. A
            # write target followed by `(` is its column list, not a call.
            return i
        self._mentions.append(_Mention(entity, written, target))
        i += 1
        if self._keyword(i) == "as":
            i += 1
        alias = self._keyword(i)
        if alias is not None and alias not in _NOT_AN_ALIAS:
            self._frames[-1].aliases[alias] = entity
            i += 1
        return i

    def _resolve(self, name: _Token) -> str | None:
        """An entity name, or a path over an alias in scope (``o.lines``); in
        SQL a table name, whose schema prefix does not decide (``public.orders``)."""
        if self._language is _Language.SQL:
            table = name.segments[-1]
            return self._entities.table_entity(table.text, quoted=table.quoted)
        head, *path = (segment.text for segment in name.segments)
        if not path:
            return self._entities.jpql_entity(head)
        scope = next((f.aliases for f in reversed(self._frames) if head.lower() in f.aliases), None)
        if scope is None:
            return self._entities.jpql_entity(name.text)
        entity = scope[head.lower()]
        for field_name in path:
            entity = self._entities.field_target(entity, field_name)
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
