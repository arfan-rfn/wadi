"""The source oracle against wadi's db sinks, site by site (§5.2.17, criterion 4, C4).

    uv run python -m wadi_testing.measure.reconcile_repository_sites \\
        --oracle sites.json --exports <dir-or-files>... \\
        [--published snapshot.ndjson] [--json out.json]

``--oracle`` is a stored run of `repository_oracle`. ``--exports`` names
export JSON files (`ServiceExport`), or directories whose `*.json` are
exports, such as the ones `e2e/test_baseline_snapshot.py` writes under
``WADI_BASELINE_EXPORT_DIR``. Each export is named by its file stem, or by
its directory when the file is `export.json` (the `sbt test` layout).

A wadi site is one distinct `call_id` among an export's `kind=db` sink rows,
the accounting unit of §5.2.17 (B5). Its file is its method's `filename` and
its line is its CFG node's, and the method called is `db.method_name`
(the node's callee on a pre-2.14.0 export, which has no `db` object).

Matching is by site, never by count: each wadi site pairs with at most one
oracle site on (file suffix, line, method name), so two `count()` calls on
one line are two pairs or a visible miss, and equal totals can never hide a
swap. The output is three lists, one site per line, each meant to be opened:

* **agree**: the same call seen by both;
* **oracle-only**: a call in source that wadi did not tag, the C4 case an
  export alone can never show. Each says whether its line sits inside a
  method the export holds (``in_exported_method``). The export is the
  endpoint-reachable closure, so a call outside it is unreached code (or an
  unrooted entry point, §5.4.2 T4); a call inside it that carries no sink is
  the omission criterion 4 exists to find;
* **wadi-only**: a db sink the oracle did not find, either an oracle blind
  spot (see its docstring) or a sink on something that is not a call.

Two export facts are folded before matching, and both are counted:

* A library staged under `wadi-libs/<dir>/` (§5.2.6) is parsed into every
  dependent, so one source call is a sink in each export. The first copy is
  matched, the rest are listed as ``library_copies``.
* A CFG node carries its statement's lines, not its call's, so a call on the
  second line of a multi-line statement matches on the node's span after
  every exact line has had its chance (``agree_by_span``).

**What an agreement is then compared on (review D6).** A location match
says nothing about whether wadi named the right entity or verb, so each
agreed site is compared twice more, and every disagreement is listed with
both sides:

* **Entity.** The oracle's simple name, read from the repository's type
  argument, against the simple name of the export's
  ``entity_type_full_name``: the type argument wadi bound, which is the
  entity it publishes for every site that is not a query. A wadi entity of
  None is ``withheld`` and never an agreement, even where the oracle is
  unbound too. A simple name cannot tell two classes of one name apart.
* **Operation.** The export carries no operation; the worker decides it.
  Wadi's claim is therefore read from what the snapshot published: the
  ``entity_access_sites`` on its ICFG nodes, from the bundle that
  ``GET /snapshots/{id}/export`` streams (``--published``). A site pairs with
  its reading on (service, file, line, repository, method), in order, so an
  export file must be named after its service, as the baseline harness
  names them; an export no published service is named after is listed. A
  db node in a flow with no site for the call is wadi's ``none`` (flush).
  The two are compared only where neither reads a query
  (``agree_operation`` / ``operation_disagree``): the oracle does not read
  query text, so two query readings are ``both_query`` and not compared, and
  a query on one side only is ``one_sided_query`` and listed. A site with no
  reading (no ``--published``, or in no endpoint flow) is ``unpublished``.

Both comparisons are ``not_read`` for a format-1 oracle run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from wadi_contracts import EntityAccessBasis, EntityOperation, Icfg, ServiceBoundary, SinkKind
from wadi_joern_client.export import ServiceExport
from wadi_testing.measure.repository_oracle import (
    OracleOperation,
    RepositoryCallSite,
    describe,
    load_sites,
)

#: Where §5.2.6 stages a library inside a dependent's parse root.
STAGED_LIBRARY_PREFIX = "wadi-libs/"


@dataclass(frozen=True)
class WadiSite:
    """One `kind=db` sink of an export: a distinct `call_id`."""

    export: str
    call_id: int
    file: str
    line: int
    line_end: int
    method: str
    repository: str | None
    enclosing: str
    #: The type argument wadi bound, qualified; None = undetermined.
    entity: str | None = None
    #: The type argument as written, kept when it did not resolve.
    entity_type_text: str | None = None

    @property
    def source_file(self) -> str:
        """``file`` with a staged library's prefix removed, as it sits in its repo."""
        return self.file.removeprefix(STAGED_LIBRARY_PREFIX)


@dataclass(frozen=True)
class MethodSpan:
    """The lines of one exported method, to place an oracle-only site."""

    export: str
    file: str
    line: int
    line_end: int


@dataclass(frozen=True)
class Agreement:
    oracle: RepositoryCallSite
    wadi: WadiSite
    by_span: bool


class EntityVerdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    WITHHELD = "withheld"
    """Wadi left the entity undetermined: an honest gap, not an agreement."""
    NOT_READ = "not-read"
    """A format-1 oracle run, which read no entity."""


class OperationVerdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    ONE_SIDED_QUERY = "one-sided-query"
    """One side reads a query and the other a name: listed, not compared."""
    BOTH_QUERY = "both-query"
    """Both read a query, whose verb the oracle does not read: not compared."""
    UNPUBLISHED = "unpublished"
    """Wadi published no reading for the site: no snapshot, or in no flow."""
    NOT_READ = "not-read"
    """A format-1 oracle run, which read no operation."""


@dataclass(frozen=True)
class SiteComparison:
    """One agreed site compared on entity and operation, with both sides."""

    agreement: Agreement
    oracle_entity: str | None
    wadi_entity: str | None
    entity: EntityVerdict
    oracle_operation: str | None
    #: `create-or-update`, `none` (flush), `query-text:<verbs>` for a query;
    #: None when nothing was published.
    wadi_operation: str | None
    operation: OperationVerdict


@dataclass(frozen=True)
class PublishedReading:
    """What a snapshot published for one repository call (an ICFG site)."""

    basis: EntityAccessBasis
    operations: tuple[EntityOperation, ...]


#: (service, file, line, repository, method): where an export site meets its reading.
type SiteKey = tuple[str, str, int, str, str]


@dataclass(frozen=True)
class Published:
    """Every repository site a snapshot published, once per ICFG node."""

    readings: dict[SiteKey, list[PublishedReading]]
    #: (service, file, line) of every db node in some endpoint flow.
    in_flow: set[tuple[str, str, int]]
    services: set[str]


@dataclass(frozen=True)
class Reconciliation:
    agree: list[Agreement]
    oracle_only: list[RepositoryCallSite]
    #: The oracle-only sites whose line lies inside a method the export holds.
    in_exported_method: list[RepositoryCallSite]
    wadi_only: list[WadiSite]
    library_copies: list[WadiSite]
    #: One per agreement, in the same order.
    compared: list[SiteComparison] = field(default_factory=list[SiteComparison])
    #: Exports named after no service of the published snapshot.
    exports_without_published_service: list[str] = field(default_factory=list[str])

    @property
    def entity_disagreements(self) -> list[SiteComparison]:
        return [c for c in self.compared if c.entity is EntityVerdict.DISAGREE]

    @property
    def entity_withheld(self) -> list[SiteComparison]:
        return [c for c in self.compared if c.entity is EntityVerdict.WITHHELD]

    @property
    def operation_disagreements(self) -> list[SiteComparison]:
        listed = (OperationVerdict.DISAGREE, OperationVerdict.ONE_SIDED_QUERY)
        return [c for c in self.compared if c.operation in listed]

    def totals(self) -> dict[str, int]:
        entity = Counter(c.entity for c in self.compared)
        operation = Counter(c.operation for c in self.compared)
        return {
            "agree": len(self.agree),
            "oracle_only": len(self.oracle_only),
            "oracle_only_in_exported_method": len(self.in_exported_method),
            "wadi_only": len(self.wadi_only),
            "oracle_sites": len(self.agree) + len(self.oracle_only),
            "wadi_sites": len(self.agree) + len(self.wadi_only),
            "library_copies": len(self.library_copies),
            "agree_by_span": sum(agreement.by_span for agreement in self.agree),
            "agree_entity": entity[EntityVerdict.AGREE],
            "entity_disagree": entity[EntityVerdict.DISAGREE],
            "entity_withheld": entity[EntityVerdict.WITHHELD],
            "entity_not_read": entity[EntityVerdict.NOT_READ],
            "agree_operation": operation[OperationVerdict.AGREE],
            "operation_disagree": operation[OperationVerdict.DISAGREE],
            "operation_one_sided_query": operation[OperationVerdict.ONE_SIDED_QUERY],
            "operation_both_query": operation[OperationVerdict.BOTH_QUERY],
            "operation_unpublished": operation[OperationVerdict.UNPUBLISHED],
            "operation_not_read": operation[OperationVerdict.NOT_READ],
        }


def wadi_sites(export: ServiceExport, name: str) -> list[WadiSite]:
    """Every distinct db call site in ``export``: file from its method, line from its node."""
    methods = {method.id: method for method in export.methods}
    nodes = {node.id: node for cfg in export.cfgs for node in cfg.nodes}
    sites: dict[int, WadiSite] = {}
    for sink in export.sinks:
        if sink.kind != "db" or sink.call_id in sites:
            continue
        method = methods[sink.method_id]
        node = nodes.get(sink.node_id)
        if sink.db is not None:
            called = sink.db.method_name
        elif node is not None and node.call is not None:
            called = node.call.callee_full_name.split(":", 1)[0].rsplit(".", 1)[-1]
        else:
            called = "?"
        sites[sink.call_id] = WadiSite(
            export=name,
            call_id=sink.call_id,
            file=method.filename,
            # No node: the method's own span, so the site can still meet its
            # oracle twin on the span pass and says so (`by_span`).
            line=node.line if node is not None else method.line,
            line_end=node.line_end if node is not None else method.line_end,
            method=called,
            repository=sink.db.repository if sink.db is not None else None,
            enclosing=method.full_name,
            entity=sink.db.entity_type_full_name if sink.db is not None else None,
            entity_type_text=sink.db.entity_type_text if sink.db is not None else None,
        )
    return sorted(sites.values(), key=lambda s: (s.file, s.line, s.call_id))


def method_spans(export: ServiceExport, name: str) -> list[MethodSpan]:
    """Every exported method with a known line span."""
    return [
        MethodSpan(name, method.filename, method.line, method.line_end)
        for method in export.methods
        if method.line > 0
    ]


def reconcile(
    oracle: Sequence[RepositoryCallSite],
    wadi: Sequence[WadiSite],
    methods: Sequence[MethodSpan] = (),
    published: Published | None = None,
) -> Reconciliation:
    """Pair each wadi site with at most one oracle site on (file suffix, line, method).

    Two passes. The exact line first, for every site; then, for what is left,
    any oracle line inside the wadi node's span, nearest first. The export
    knows only the STATEMENT's lines, so a call on the second line of a
    multi-line statement can only meet its oracle site the second way.
    """
    distinct, copies = _fold_library_copies(wadi)
    by_method: dict[str, list[int]] = defaultdict(list)
    for index, site in enumerate(oracle):
        by_method[site.method].append(index)
    free = set(range(len(oracle)))
    paired: dict[int, Agreement] = {}
    for by_span in (False, True):
        for position, site in enumerate(distinct):
            if position in paired:
                continue
            last = max(site.line, site.line_end)
            candidates = [
                index
                for index in by_method.get(site.method, [])
                if index in free
                and _same_file(oracle[index].file, site.source_file)
                and (
                    site.line <= oracle[index].line <= last
                    if by_span
                    else oracle[index].line == site.line
                )
            ]
            if candidates:
                chosen = min(candidates, key=lambda index: (oracle[index].line - site.line, index))
                free.remove(chosen)
                paired[position] = Agreement(oracle[chosen], site, by_span)
    oracle_only = [site for index, site in enumerate(oracle) if index in free]
    by_basename: dict[str, list[MethodSpan]] = defaultdict(list)
    for method in methods:
        by_basename[method.file.rsplit("/", 1)[-1]].append(method)
    agree = sorted(paired.values(), key=lambda a: (a.oracle.file, a.oracle.line))
    exports = sorted({site.export for site in wadi})
    return Reconciliation(
        agree=agree,
        compared=_compare(agree, published),
        exports_without_published_service=(
            [name for name in exports if name not in published.services]
            if published is not None
            else []
        ),
        oracle_only=oracle_only,
        in_exported_method=[
            site
            for site in oracle_only
            if _inside_any(site, by_basename.get(site.file.rsplit("/", 1)[-1], []))
        ],
        wadi_only=[site for position, site in enumerate(distinct) if position not in paired],
        library_copies=copies,
    )


def load_published(path: Path) -> Published:
    """The repository sites a snapshot bundle (`GET /snapshots/{id}/export`) published.

    Only ``service_boundary`` and ``icfg`` records are read. A node two
    endpoints' graphs both hold is one node, so its sites are read once.
    """
    names: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    nodes: list[tuple[str, str, int, list[tuple[str, str, PublishedReading]]]] = []
    with path.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            record: dict[str, Any] = json.loads(line)
            kind = record.get("kind")
            if kind == "service_boundary":
                boundary = ServiceBoundary.model_validate(record["artifact"])
                names[boundary.service_id] = boundary.name
            elif kind == "icfg":
                icfg = Icfg.model_validate(record["artifact"])
                for node in icfg.nodes:
                    if (icfg.service_id, node.id) in seen:
                        continue
                    seen.add((icfg.service_id, node.id))
                    if node.sink is not SinkKind.DB and not node.entity_access_sites:
                        continue
                    sites = [
                        (
                            site.repository,
                            site.method_name,
                            PublishedReading(
                                basis=site.basis,
                                operations=tuple(
                                    sorted(
                                        {access.operation for access in site.accesses},
                                        key=list(EntityOperation).index,
                                    )
                                ),
                            ),
                        )
                        for site in node.entity_access_sites
                    ]
                    nodes.append((icfg.service_id, node.anchor.file, node.anchor.start_line, sites))
    readings: dict[SiteKey, list[PublishedReading]] = defaultdict(list)
    in_flow: set[tuple[str, str, int]] = set()
    for service_id, file, line, sites in nodes:
        service = names.get(service_id, service_id)
        in_flow.add((service, file, line))
        for repository, method, reading in sites:
            readings[(service, file, line, repository, method)].append(reading)
    return Published(readings=dict(readings), in_flow=in_flow, services=set(names.values()))


def _compare(agree: Sequence[Agreement], published: Published | None) -> list[SiteComparison]:
    """Each agreement compared on entity and operation (see the module docstring)."""
    readings = _pair_readings(agree, published)
    compared: list[SiteComparison] = []
    for index, agreement in enumerate(agree):
        oracle, wadi = agreement.oracle, agreement.wadi
        wadi_entity = _simple(wadi.entity) if wadi.entity is not None else None
        if oracle.operation is None:
            entity_verdict = EntityVerdict.NOT_READ
        elif wadi_entity is None:
            entity_verdict = EntityVerdict.WITHHELD
        elif oracle.entity == wadi_entity:
            entity_verdict = EntityVerdict.AGREE
        else:
            entity_verdict = EntityVerdict.DISAGREE
        wadi_operation, wadi_query = _wadi_operation(wadi, readings[index], published)
        if oracle.operation is None:
            operation_verdict = OperationVerdict.NOT_READ
        elif wadi_operation is None:
            operation_verdict = OperationVerdict.UNPUBLISHED
        elif (oracle.operation is OracleOperation.QUERY) and wadi_query:
            operation_verdict = OperationVerdict.BOTH_QUERY
        elif (oracle.operation is OracleOperation.QUERY) or wadi_query:
            operation_verdict = OperationVerdict.ONE_SIDED_QUERY
        elif oracle.operation.value == wadi_operation:
            operation_verdict = OperationVerdict.AGREE
        else:
            operation_verdict = OperationVerdict.DISAGREE
        compared.append(
            SiteComparison(
                agreement=agreement,
                oracle_entity=oracle.entity,
                wadi_entity=wadi_entity,
                entity=entity_verdict,
                oracle_operation=oracle.operation.value if oracle.operation else None,
                wadi_operation=wadi_operation,
                operation=operation_verdict,
            )
        )
    return compared


def _pair_readings(
    agree: Sequence[Agreement], published: Published | None
) -> list[PublishedReading | None]:
    """Each agreement's published reading, paired in call-id order within its key."""
    paired: list[PublishedReading | None] = [None] * len(agree)
    if published is None:
        return paired
    by_key: dict[SiteKey, list[int]] = defaultdict(list)
    for index, agreement in enumerate(agree):
        wadi = agreement.wadi
        if wadi.repository is not None:
            key = (wadi.export, wadi.file, wadi.line, wadi.repository, wadi.method)
            by_key[key].append(index)
    for key, indexes in by_key.items():
        indexes.sort(key=lambda index: agree[index].wadi.call_id)
        for index, reading in zip(indexes, published.readings.get(key, []), strict=False):
            paired[index] = reading
    return paired


def _wadi_operation(
    wadi: WadiSite, reading: PublishedReading | None, published: Published | None
) -> tuple[str | None, bool]:
    """(wadi's published operation as text, whether it read a query); None = unpublished."""
    if reading is not None:
        verbs = "+".join(operation.value for operation in reading.operations)
        if reading.basis is EntityAccessBasis.QUERY_TEXT:
            return f"query-text:{verbs}", True
        return verbs, False
    if published is None or wadi.repository is None:
        return None, False
    key = (wadi.export, wadi.file, wadi.line, wadi.repository, wadi.method)
    if key not in published.readings and (wadi.export, wadi.file, wadi.line) in published.in_flow:
        # A db node in a flow that carries no site for this call: the call is
        # no entity operation (flush), which the oracle calls `none`.
        return OracleOperation.NONE.value, False
    return None, False


def _simple(name: str) -> str:
    return name.replace("$", ".").rsplit(".", 1)[-1]


def export_files(paths: Iterable[Path]) -> list[Path]:
    """The files named, and the `*.json` in each directory named."""
    return [
        file
        for path in paths
        for file in (sorted(path.glob("*.json")) if path.is_dir() else [path])
    ]


def load_exports(files: Iterable[Path]) -> tuple[list[WadiSite], list[MethodSpan]]:
    """The wadi sites and method spans of every export file."""
    sites: list[WadiSite] = []
    spans: list[MethodSpan] = []
    for file in files:
        export = ServiceExport.model_validate(json.loads(file.read_text()))
        name = file.parent.name if file.stem == "export" else file.stem
        sites.extend(wadi_sites(export, name))
        spans.extend(method_spans(export, name))
    return sites, spans


def describe_wadi(site: WadiSite) -> str:
    repository = (site.repository or "?").rsplit(".", 1)[-1]
    return (
        f"{site.export}: {site.file}:{site.line}  {site.method}()  <{repository}>"
        f"  in {site.enclosing.split(':', 1)[0]}  call_id={site.call_id}"
    )


def describe_comparison(compared: SiteComparison, on: str) -> str:
    """One disagreement: where, then each side's reading of ``on`` (entity | operation)."""
    if on == "entity":
        oracle, wadi = compared.oracle_entity, compared.wadi_entity
        text = compared.agreement.wadi.entity_type_text
        written = f" (written {text})" if wadi is None and text else ""
        sides = f"oracle {oracle or '-'}  wadi {wadi or 'undetermined'}{written}"
    else:
        sides = f"oracle {compared.oracle_operation}  wadi {compared.wadi_operation}"
    wadi_site = compared.agreement.wadi
    return (
        f"  {describe(compared.agreement.oracle)}  = {wadi_site.export}#{wadi_site.call_id}"
        f"\n      {sides}"
    )


def to_json(result: Reconciliation) -> dict[str, Any]:
    def compared_row(compared: SiteComparison) -> dict[str, Any]:
        return {
            "oracle": asdict(compared.agreement.oracle),
            "wadi": asdict(compared.agreement.wadi),
            "by_span": compared.agreement.by_span,
            "entity": {
                "oracle": compared.oracle_entity,
                "wadi": compared.wadi_entity,
                "verdict": compared.entity.value,
            },
            "operation": {
                "oracle": compared.oracle_operation,
                "wadi": compared.wadi_operation,
                "verdict": compared.operation.value,
            },
        }

    return {
        "totals": result.totals(),
        "agree": [compared_row(compared) for compared in result.compared],
        "entity_disagreements": [compared_row(c) for c in result.entity_disagreements],
        "entity_withheld": [compared_row(c) for c in result.entity_withheld],
        "operation_disagreements": [compared_row(c) for c in result.operation_disagreements],
        "exports_without_published_service": result.exports_without_published_service,
        "oracle_only": [asdict(site) for site in result.oracle_only],
        "oracle_only_in_exported_method": [asdict(site) for site in result.in_exported_method],
        "wadi_only": [asdict(site) for site in result.wadi_only],
        "library_copies": [asdict(site) for site in result.library_copies],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wadi_testing.measure.reconcile_repository_sites",
        description="Reconcile oracle repository call sites with wadi's db sinks, site by site.",
    )
    parser.add_argument("--oracle", type=Path, required=True, help="a repository_oracle --json")
    parser.add_argument(
        "--exports", type=Path, nargs="+", required=True, help="export files or directories"
    )
    parser.add_argument(
        "--published",
        type=Path,
        help="the snapshot bundle `GET /snapshots/{id}/export` streams; without it no "
        "operation is compared",
    )
    parser.add_argument("--json", type=Path, help="write the lists and the totals here")
    args = parser.parse_args(argv)

    files = export_files(args.exports)
    if not files:
        parser.error(f"no export JSON in {' '.join(map(str, args.exports))}")
    sites, spans = load_exports(files)
    published = load_published(args.published) if args.published is not None else None
    result = reconcile(load_sites(args.oracle), sites, spans, published)
    in_method = set(result.in_exported_method)

    print(f"agree ({len(result.agree)})")
    for agreement in result.agree:
        span = f"  (wadi line {agreement.wadi.line}, by span)" if agreement.by_span else ""
        wadi = agreement.wadi
        print(f"  {describe(agreement.oracle)}  = {wadi.export}#{wadi.call_id}{span}")
    print(f"\noracle-only ({len(result.oracle_only)})")
    for site in result.oracle_only:
        where = "in an exported method" if site in in_method else "outside the export"
        print(f"  {describe(site)}  [{where}]")
    print(f"\nwadi-only ({len(result.wadi_only)})")
    for site in result.wadi_only:
        print(f"  {describe_wadi(site)}")
    print(f"\nentity disagreements ({len(result.entity_disagreements)})")
    for compared in result.entity_disagreements:
        print(describe_comparison(compared, "entity"))
    print(f"\nentity withheld by wadi ({len(result.entity_withheld)})")
    for compared in result.entity_withheld:
        print(describe_comparison(compared, "entity"))
    print(f"\noperation disagreements ({len(result.operation_disagreements)})")
    for compared in result.operation_disagreements:
        print(describe_comparison(compared, "operation"))
    totals = result.totals()
    print(
        f"\ntotals: agree {totals['agree']}   oracle-only {totals['oracle_only']}"
        f" ({totals['oracle_only_in_exported_method']} in an exported method)"
        f"   wadi-only {totals['wadi_only']}"
    )
    print(
        f"  oracle sites {totals['oracle_sites']}   wadi sites {totals['wadi_sites']}"
        f"   library copies folded {totals['library_copies']}"
        f"   agreed by span {totals['agree_by_span']}"
    )
    print(
        f"  entity: agree {totals['agree_entity']}   disagree {totals['entity_disagree']}"
        f"   withheld {totals['entity_withheld']}   not read {totals['entity_not_read']}"
    )
    print(
        f"  operation: agree {totals['agree_operation']}"
        f"   disagree {totals['operation_disagree']}"
        f"   one-sided query {totals['operation_one_sided_query']}"
        f"   both query {totals['operation_both_query']}"
        f"   unpublished {totals['operation_unpublished']}"
        f"   not read {totals['operation_not_read']}"
    )
    if published is None:
        print("  no --published snapshot: no operation was compared")
    for name in result.exports_without_published_service:
        print(f"  export {name!r} is named after no service of the published snapshot")
    if args.json is not None:
        output: Path = args.json
        output.write_text(json.dumps(to_json(result), indent=2) + "\n")
        print(f"wrote {output}")
    return 0


def _fold_library_copies(wadi: Sequence[WadiSite]) -> tuple[list[WadiSite], list[WadiSite]]:
    """(distinct sites, later copies of a staged library's sites).

    A copy is the same (source file, line, method, ordinal on that line) in a
    second export. The ordinal keeps two real calls on one library line apart.
    """
    distinct: list[WadiSite] = []
    copies: list[WadiSite] = []
    owner: dict[tuple[str, int, str, int], str] = {}
    ordinal: Counter[tuple[str, str, int, str]] = Counter()
    for site in wadi:
        if not site.file.startswith(STAGED_LIBRARY_PREFIX):
            distinct.append(site)
            continue
        line_key = (site.export, site.source_file, site.line, site.method)
        key = (site.source_file, site.line, site.method, ordinal[line_key])
        ordinal[line_key] += 1
        if owner.setdefault(key, site.export) == site.export:
            distinct.append(site)
        else:
            copies.append(site)
    return distinct, copies


def _inside_any(site: RepositoryCallSite, methods: Sequence[MethodSpan]) -> bool:
    return any(
        method.line <= site.line <= method.line_end
        and _same_file(site.file, method.file.removeprefix(STAGED_LIBRARY_PREFIX))
        for method in methods
    )


def _same_file(oracle_file: str, wadi_file: str) -> bool:
    return oracle_file == wadi_file or oracle_file.endswith("/" + wadi_file)


if __name__ == "__main__":
    sys.exit(main())
