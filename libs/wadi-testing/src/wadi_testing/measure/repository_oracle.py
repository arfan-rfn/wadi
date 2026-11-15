"""Repository call sites, read from Java source (§5.2.17, criterion 4, C4).

    uv run python -m wadi_testing.measure.repository_oracle <source-root> [--json out.json]

Design success criterion 4 asks for an independent count of repository call
sites, with every disagreement against wadi opened and explained. The count
has to come from source: an export cannot reveal a call its producer omitted
(C4), so this module never reads one. `reconcile_repository_sites` puts the
two side by side, site by site.

What it does, over comment- and literal-stripped text:

* **Repository interfaces.** An interface whose `extends` chain reaches a
  Spring Data marker (`SPRING_DATA_MARKERS`), directly or through project
  interfaces, resolved by simple name across the whole source root (Q10:
  `IssueRepository extends BaseRepository<Issue>`). A marker counts only
  where the file imports it from `org.springframework.data` or writes it
  qualified.
* **Repository variables.** Every `<Type> <name>` declaration of such a type
  (or of a marker itself): fields, `@Autowired` or constructor-injected, method
  and lambda parameters, locals.
* **Call sites.** Every `<name>.<method>(` on those variables, lambda bodies
  included (`in_lambda`), and every unqualified or `this.` call inside a
  repository interface's `default` method (golden 32).
* **Skipped trees.** `src/test/**`, `.evosuite-work/**`, and `target/**` /
  `build/**` outside a `src` tree.

It is a regex and lexer oracle, not a parser, and every disagreement it causes
is opened by hand, so it stays simple. What it does NOT see:

* A receiver that is not a plain variable: `getRepository().save(x)`,
  `repositories.get(0).save(x)`, a chained builder.
* A variable whose type is not written: `var repo = ...`, an untyped lambda
  parameter (`repos.forEach(r -> r.save(x))`), a field typed by a generic
  parameter (`R repository` where `R extends JpaRepository<...>`).
* A field declared in a superclass in another file: variables are scoped to
  the file that declares them.
* Method references (`orderRepository::save`). These are invocations, so they
  are listed apart in `method_references` rather than dropped.
* Repositories declared outside the source root (a jar), interfaces made
  repositories by `@RepositoryDefinition`, and any non-Java source.

And what it over-reads, each of which shows up as an oracle-only site:

* Scope is the file, not the method: a name declared with a repository type
  anywhere in a file is a repository variable everywhere in it. When one name
  has several repository types, the nearest declaration before the call wins.
* Simple-name resolution: two project interfaces sharing a simple name are one
  name, a repository if either is.
* `in_lambda` is lexical (`->` bodies); an anonymous class is not a lambda.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

#: Spring Data interfaces that make an interface a repository when its
#: `extends` chain reaches one, written from the Spring Data module list and
#: not copied from the sink pass, so a marker the pass lacks is a disagreement
#: rather than a shared blind spot. A name counts only where the file imports
#: it from `org.springframework.data` (or writes it qualified): JGit's
#: `Repository` is not one.
SPRING_DATA_MARKERS = frozenset(
    {
        "Repository",
        "CrudRepository",
        "ListCrudRepository",
        "PagingAndSortingRepository",
        "ListPagingAndSortingRepository",
        "JpaRepository",
        "MongoRepository",
        "ReactiveCrudRepository",
        "ReactiveSortingRepository",
        "ReactiveMongoRepository",
        "RxJava2CrudRepository",
        "RxJava3CrudRepository",
        "RxJava2SortingRepository",
        "RxJava3SortingRepository",
        "CoroutineCrudRepository",
        "CoroutineSortingRepository",
        "R2dbcRepository",
        "ElasticsearchRepository",
        "Neo4jRepository",
        "ReactiveNeo4jRepository",
        "CassandraRepository",
        "ReactiveCassandraRepository",
        "CouchbaseRepository",
        "ReactiveCouchbaseRepository",
        "KeyValueRepository",
        "RevisionRepository",
        "EnversRevisionRepository",
    }
)

#: The JSON document's own version, so a stored oracle run says what wrote it.
ORACLE_FORMAT = "1"

_SPRING_DATA_PACKAGE = "org.springframework.data."
_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")

_IDENT = r"[A-Za-z_$][\w$]*"
_IMPORT = re.compile(r"(?m)^\s*import\s+(static\s+)?([\w$.]+(?:\.\*)?)\s*;")
_INTERFACE = re.compile(rf"(?<![\w$@])interface\s+({_IDENT})")
_TYPE_HEADER = re.compile(rf"(?<![\w$@])(?:class|interface|enum|record)\s+({_IDENT})")
_INTERFACE_HEADER = re.compile(r"(?<![\w$@])interface\b")
_DEFAULT_MODIFIER = re.compile(r"\bdefault\b")
_THROWS = re.compile(r"\bthrows\b[^(){}]*$")
_TRAILING_IDENT = re.compile(rf"({_IDENT})$")
_TRAILING_NEW = re.compile(r"(?<![\w$])new\s*$")
_SWITCH_RULE = re.compile(r"\s*(?:case|default)\b")
_ARROW = re.compile(r"->")
_UNQUALIFIED_CALL = re.compile(rf"(?<![\w$.])(this\s*\.\s*)?({_IDENT})\s*\(")

#: Words a `name(` can follow that are not a method name.
_NOT_A_METHOD = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "synchronized",
        "try",
        "return",
        "new",
        "else",
        "throw",
        "assert",
        "super",
        "this",
    }
)


@dataclass(frozen=True)
class RepositoryCallSite:
    """One call on a repository, where the source wrote it.

    ``receiver`` is the variable as written, `this` for `this.save(...)`, and
    empty for an unqualified call inside a repository's own default method.
    """

    module: str
    file: str
    line: int
    repository: str
    receiver: str
    method: str
    enclosing_class: str | None
    enclosing_method: str | None
    in_lambda: bool


@dataclass(frozen=True)
class OracleReport:
    source_root: str
    files_scanned: int
    repositories: list[str]
    sites: list[RepositoryCallSite]
    method_references: list[RepositoryCallSite]

    def totals(self) -> dict[str, Any]:
        return {
            "sites": len(self.sites),
            "in_lambda": sum(site.in_lambda for site in self.sites),
            "method_references": len(self.method_references),
            "by_module": dict(sorted(Counter(site.module for site in self.sites).items())),
        }


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    name: str | None
    header: str


@dataclass(frozen=True)
class _JavaFile:
    path: Path
    relative: str
    text: str
    imports: dict[str, str]
    wildcard_imports: list[str]
    static_imports: set[str]


#: (offset, receiver, repository, method) of one call, before its context.
type _Call = tuple[int, str, str, str]


def scan(source_root: Path) -> OracleReport:
    """Every repository call site under ``source_root``, in file then source order."""
    root = source_root.resolve()
    files = [
        _load(path, root)
        for path in sorted(root.rglob("*.java"))
        if not _excluded(path.relative_to(root).parts)
    ]
    repositories = _repository_interfaces(_interface_parents(files))

    sites: list[RepositoryCallSite] = []
    references: list[RepositoryCallSite] = []
    modules: dict[Path, str] = {}
    for java in files:
        module = _module_of(java.path.parent, root, modules)
        file_sites, file_references = _sites_in(java, repositories, module)
        sites.extend(file_sites)
        references.extend(file_references)
    return OracleReport(
        source_root=str(source_root),
        files_scanned=len(files),
        repositories=sorted(repositories),
        sites=sites,
        method_references=references,
    )


def strip_java(source: str) -> str:
    """``source`` with every comment and literal body blanked to spaces.

    Length and newlines are kept, so an offset in the result is the same
    offset, line and column in the file. Quotes stay, so `f("x")` is still a
    call with an argument. A lexer rather than three regexes: a `//` inside a
    string, or a `"` inside a comment, defeats any fixed order of substitutions.
    """
    out = list(source)
    index, length = 0, len(source)

    def blank(start: int, end: int) -> None:
        for position in range(start, min(end, length)):
            if out[position] != "\n":
                out[position] = " "

    while index < length:
        char = source[index]
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = length if end < 0 else end
            blank(index, end)
            index = end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
            blank(index, end)
            index = end
        elif source.startswith('"""', index):
            end = index + 3
            while end < length and not source.startswith('"""', end):
                end += 2 if source[end] == "\\" else 1
            blank(index + 3, end)
            index = end + 3
        elif char in "\"'":
            end = index + 1
            while end < length and source[end] != char and source[end] != "\n":
                end += 2 if source[end] == "\\" else 1
            blank(index + 1, end)
            index = end + 1
        else:
            index += 1
    return "".join(out)


def to_json(report: OracleReport) -> dict[str, Any]:
    return {
        "oracle_format": ORACLE_FORMAT,
        "source_root": report.source_root,
        "files_scanned": report.files_scanned,
        "repositories": report.repositories,
        "totals": report.totals(),
        "sites": [asdict(site) for site in report.sites],
        "method_references": [asdict(site) for site in report.method_references],
    }


def load_sites(path: Path) -> list[RepositoryCallSite]:
    """The sites of a stored oracle run (the reconciler's input)."""
    document = json.loads(path.read_text())
    return [RepositoryCallSite(**row) for row in document["sites"]]


def describe(site: RepositoryCallSite) -> str:
    """One line per site: where it is, what it calls, and from where."""
    receiver = f"{site.receiver}." if site.receiver else ""
    where = ".".join(part for part in (site.enclosing_class, site.enclosing_method) if part)
    lambda_mark = "  [lambda]" if site.in_lambda else ""
    return (
        f"{site.file}:{site.line}  {receiver}{site.method}()  "
        f"<{site.repository}>  in {where or '?'}{lambda_mark}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wadi_testing.measure.repository_oracle",
        description="Count Spring Data repository call sites from Java source.",
    )
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--json", type=Path, help="write every site and the totals here")
    args = parser.parse_args(argv)

    source_root: Path = args.source_root
    if not source_root.is_dir():
        parser.error(f"not a directory: {source_root}")
    report = scan(source_root)
    for site in report.sites:
        print(describe(site))
    for reference in report.method_references:
        print(f"method reference (not a site): {describe(reference)}")
    totals = report.totals()
    print(f"\nfiles: {report.files_scanned}   repositories: {len(report.repositories)}")
    print(
        f"sites: {totals['sites']}   in_lambda: {totals['in_lambda']}"
        f"   method_references: {totals['method_references']}"
    )
    for module, count in totals["by_module"].items():
        print(f"  {module}: {count}")
    if args.json is not None:
        output: Path = args.json
        output.write_text(json.dumps(to_json(report), indent=2) + "\n")
        print(f"wrote {output}")
    return 0


def _excluded(parts: tuple[str, ...]) -> bool:
    """`src/test/**`, `.evosuite-work/**`, and `target/**` / `build/**` outside a
    `src` tree, so a package named `build` is still source."""
    if ".evosuite-work" in parts:
        return True
    if ("src", "test") in pairwise(parts):
        return True
    outside_src = parts[: parts.index("src")] if "src" in parts else parts[:-1]
    return any(part in ("target", "build") for part in outside_src)


def _load(path: Path, root: Path) -> _JavaFile:
    text = strip_java(path.read_text(encoding="utf-8", errors="replace"))
    imports: dict[str, str] = {}
    wildcards: list[str] = []
    static: set[str] = set()
    for match in _IMPORT.finditer(text):
        name = match.group(2)
        if match.group(1):
            static.add(name.rsplit(".", 1)[-1])
        elif name.endswith(".*"):
            wildcards.append(name[:-2])
        else:
            imports[name.rsplit(".", 1)[-1]] = name
    return _JavaFile(path, path.relative_to(root).as_posix(), text, imports, wildcards, static)


def _interface_parents(files: list[_JavaFile]) -> dict[str, list[tuple[_JavaFile, str]]]:
    """Simple interface name -> every (declaring file, parent as written)."""
    parents: dict[str, list[tuple[_JavaFile, str]]] = {}
    for java in files:
        for match in _INTERFACE.finditer(java.text):
            header_end = java.text.find("{", match.end())
            if header_end < 0:
                continue
            declared = parents.setdefault(match.group(1), [])
            for parent in _extends_clause(java.text[match.end() : header_end]):
                declared.append((java, parent))
    return parents


def _extends_clause(header: str) -> list[str]:
    """The parents of `interface X<...> extends A<..>, b.B permits ...`, as written."""
    rest = header.strip()
    if rest.startswith("<"):
        rest = rest[_balanced_end(rest, 0, "<", ">") :].strip()
    if not rest.startswith("extends"):
        return []
    rest = re.split(r"\bpermits\b", rest[len("extends") :], maxsplit=1)[0]
    return [part.split("<", 1)[0].strip() for part in _top_level_split(rest) if part.strip()]


def _repository_interfaces(parents: dict[str, list[tuple[_JavaFile, str]]]) -> set[str]:
    resolved: dict[str, bool] = {}

    def reaches_marker(name: str, seen: frozenset[str]) -> bool:
        if name in resolved:
            return resolved[name]
        answer = any(
            _is_spring_marker(java, parent)
            or (
                (simple := parent.rsplit(".", 1)[-1]) in parents
                and simple not in seen
                and reaches_marker(simple, seen | {simple})
            )
            for java, parent in parents[name]
        )
        resolved[name] = answer
        return answer

    return {name for name in parents if reaches_marker(name, frozenset({name}))}


def _is_spring_marker(java: _JavaFile, written: str) -> bool:
    """Whether a type name as written in ``java`` is a Spring Data marker."""
    simple = written.rsplit(".", 1)[-1]
    if simple not in SPRING_DATA_MARKERS:
        return False
    if "." in written:
        return written.startswith(_SPRING_DATA_PACKAGE)
    imported = java.imports.get(simple)
    if imported is not None:
        return imported.startswith(_SPRING_DATA_PACKAGE)
    return any(package.startswith(_SPRING_DATA_PACKAGE) for package in java.wildcard_imports)


def _sites_in(
    java: _JavaFile, repositories: set[str], module: str
) -> tuple[list[RepositoryCallSite], list[RepositoryCallSite]]:
    """(call sites, method references) in one file."""
    text = java.text
    declarations = _repository_variables(java, repositories)
    blocks = _blocks(text)
    calls: list[_Call] = []
    references: list[_Call] = []
    if declarations:
        names = "|".join(
            map(re.escape, sorted({d[1] for d in declarations}, key=lambda n: (-len(n), n)))
        )
        on_variable = re.compile(rf"(?<![\w$])({names})\s*(\.|::)\s*({_IDENT})\s*(\()?")
        for match in on_variable.finditer(text):
            name, separator, method = match.group(1), match.group(2), match.group(3)
            if separator == "." and match.group(4) is None:
                continue  # a field read, `repo.x`, not a call
            entry = (match.start(), name, _declared_type(declarations, name, match.start()), method)
            (calls if separator == "." else references).append(entry)
    calls.extend(_implicit_receiver_calls(java, blocks, repositories))
    if not calls and not references:
        return [], []
    lambdas = _lambda_bodies(text, blocks)
    lines = _line_starts(text)

    def record(call: _Call) -> RepositoryCallSite:
        offset, receiver, repository, method = call
        return RepositoryCallSite(
            module=module,
            file=java.relative,
            line=bisect.bisect_right(lines, offset),
            repository=repository,
            receiver=receiver,
            method=method,
            enclosing_class=_innermost(blocks, offset, "type"),
            enclosing_method=_innermost(blocks, offset, "method"),
            in_lambda=any(start <= offset < end for start, end in lambdas),
        )

    return [record(c) for c in sorted(calls)], [record(r) for r in sorted(references)]


def _implicit_receiver_calls(
    java: _JavaFile, blocks: list[_Block], repositories: set[str]
) -> list[_Call]:
    """Calls with no receiver, or `this.`, inside a repository's `default` method.

    In an interface body an unqualified call can only be the interface's own
    method or a static import (excluded), so `save(order)` in a default method
    is a call on the repository itself (golden 32, C3).
    """
    found: list[_Call] = []
    for method in blocks:
        if method.kind != "method" or not _DEFAULT_MODIFIER.search(method.header):
            continue
        owner = _innermost_block(blocks, method.start, "type")
        if owner is None or owner.name not in repositories:
            continue
        if not _INTERFACE_HEADER.search(owner.header):
            continue
        body = java.text[method.start : method.end]
        for match in _UNQUALIFIED_CALL.finditer(body):
            this, name = match.group(1), match.group(2)
            if name in _NOT_A_METHOD or name in java.static_imports:
                continue
            if not this and _TRAILING_NEW.search(body, 0, match.start()):
                continue  # `new Order(...)` constructs, it does not call
            found.append((method.start + match.start(), "this" if this else "", owner.name, name))
    return found


def _repository_variables(java: _JavaFile, repositories: set[str]) -> list[tuple[int, str, str]]:
    """(offset, variable, repository simple name) for each repository-typed declaration."""
    candidates = sorted(repositories | SPRING_DATA_MARKERS, key=lambda n: (-len(n), n))
    declaration = re.compile(
        rf"(?<![\w$])({'|'.join(map(re.escape, candidates))})"
        rf"\s*(?:<[^;{{}}()]*?>)?\s*(?:\[\s*\]\s*)*\s({_IDENT})\s*(?=[;=,):])"
    )
    found: list[tuple[int, str, str]] = []
    for match in declaration.finditer(java.text):
        type_name = match.group(1)
        if type_name in repositories or _is_spring_marker(java, type_name):
            found.append((match.start(), match.group(2), type_name))
    return found


def _declared_type(declarations: list[tuple[int, str, str]], name: str, offset: int) -> str:
    """The nearest declaration of ``name`` before ``offset``, else the first after."""
    before = [d for d in declarations if d[1] == name and d[0] <= offset]
    if before:
        return before[-1][2]
    return next(d[2] for d in declarations if d[1] == name)


def _blocks(text: str) -> list[_Block]:
    """Every `{...}` with what opened it, from one pass over the braces."""
    blocks: list[_Block] = []
    stack: list[tuple[int, str, str | None, str]] = []
    boundary = -1
    for index, char in enumerate(text):
        if char == "{":
            header = text[boundary + 1 : index]
            kind, name = _classify(header)
            stack.append((index, kind, name, header))
            boundary = index
        elif char == "}":
            if stack:
                start, kind, name, header = stack.pop()
                blocks.append(_Block(start, index, kind, name, header))
            boundary = index
        elif char == ";":
            boundary = index
    blocks.extend(
        _Block(start, len(text), kind, name, header) for start, kind, name, header in stack
    )
    return blocks


def _classify(header: str) -> tuple[str, str | None]:
    """What a `{` opens, judged from the text since the previous `;`, `{` or `}`."""
    head = header.rstrip()
    if head.endswith("->"):
        return ("other", None) if _is_switch_rule(head, len(head) - 2) else ("lambda", None)
    declared = _TYPE_HEADER.search(header)
    if declared:
        return "type", declared.group(1)
    head = _THROWS.sub("", head).rstrip()
    if not head.endswith(")"):
        return "other", None
    opening = _balanced_start(head, len(head) - 1)
    if opening < 0:
        return "other", None
    before = head[:opening].rstrip()
    name = _TRAILING_IDENT.search(before)
    if name is None or name.group(1) in _NOT_A_METHOD:
        return "other", None
    prefix = before[: name.start()].rstrip()
    if prefix.endswith(".") or _TRAILING_NEW.search(prefix):
        return "other", None  # a chained call, or an anonymous class body
    return "method", name.group(1)


def _lambda_bodies(text: str, blocks: list[_Block]) -> list[tuple[int, int]]:
    """[start, end) of every lambda body: block bodies from the brace scan,
    expression bodies up to the `,` `;` or closing bracket that ends them."""
    bodies = [(block.start, block.end) for block in blocks if block.kind == "lambda"]
    for arrow in _ARROW.finditer(text):
        if _is_switch_rule(text, arrow.start()):
            continue
        body = arrow.end()
        while body < len(text) and text[body].isspace():
            body += 1
        if body < len(text) and text[body] != "{":
            bodies.append((body, _expression_end(text, body)))
    return bodies


def _is_switch_rule(text: str, arrow: int) -> bool:
    """Whether the `->` at ``arrow`` is a `case`/`default` rule.

    Only the segment since the previous statement boundary or arrow is read,
    so the lambda in `case A -> ids.forEach(id -> ...)` is still a lambda.
    """
    start = max(text.rfind(char, 0, arrow) for char in ";{}")
    previous = text.rfind("->", 0, arrow)
    if previous >= 0:
        start = max(start, previous + 1)
    return _SWITCH_RULE.match(text, start + 1, arrow) is not None


def _expression_end(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return index
            depth -= 1
        elif char in ",;" and depth == 0:
            return index
    return len(text)


def _innermost(blocks: list[_Block], offset: int, kind: str) -> str | None:
    block = _innermost_block(blocks, offset, kind)
    return block.name if block else None


def _innermost_block(blocks: list[_Block], offset: int, kind: str) -> _Block | None:
    enclosing = [b for b in blocks if b.kind == kind and b.start < offset < b.end]
    return max(enclosing, key=lambda b: b.start) if enclosing else None


def _module_of(directory: Path, root: Path, cache: dict[Path, str]) -> str:
    """The nearest build root (pom.xml, build.gradle[.kts]) at or above ``directory``."""
    if directory in cache:
        return cache[directory]
    if any((directory / build).is_file() for build in _BUILD_FILES):
        module = directory.relative_to(root).as_posix() or "."
    elif directory == root or root not in directory.parents:
        module = "."
    else:
        module = _module_of(directory.parent, root, cache)
    cache[directory] = module
    return module


def _line_starts(text: str) -> list[int]:
    return [0, *(index + 1 for index, char in enumerate(text) if char == "\n")]


def _balanced_end(text: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _balanced_start(text: str, end: int) -> int:
    """The index of the `(` matching the `)` at ``end``, or -1."""
    depth = 0
    for index in range(end, -1, -1):
        if text[index] == ")":
            depth += 1
        elif text[index] == "(":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _top_level_split(text: str) -> list[str]:
    """Split at commas outside `<...>`."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


if __name__ == "__main__":
    sys.exit(main())
