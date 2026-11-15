"""The source oracle against wadi's db sinks, site by site (§5.2.17, criterion 4, C4).

    uv run python -m wadi_testing.measure.reconcile_repository_sites \\
        --oracle sites.json --exports <dir-or-files>... [--json out.json]

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
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wadi_joern_client.export import ServiceExport
from wadi_testing.measure.repository_oracle import RepositoryCallSite, describe, load_sites

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


@dataclass(frozen=True)
class Reconciliation:
    agree: list[Agreement]
    oracle_only: list[RepositoryCallSite]
    #: The oracle-only sites whose line lies inside a method the export holds.
    in_exported_method: list[RepositoryCallSite]
    wadi_only: list[WadiSite]
    library_copies: list[WadiSite]

    def totals(self) -> dict[str, int]:
        return {
            "agree": len(self.agree),
            "oracle_only": len(self.oracle_only),
            "oracle_only_in_exported_method": len(self.in_exported_method),
            "wadi_only": len(self.wadi_only),
            "oracle_sites": len(self.agree) + len(self.oracle_only),
            "wadi_sites": len(self.agree) + len(self.wadi_only),
            "library_copies": len(self.library_copies),
            "agree_by_span": sum(agreement.by_span for agreement in self.agree),
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
    return Reconciliation(
        agree=sorted(paired.values(), key=lambda a: (a.oracle.file, a.oracle.line)),
        oracle_only=oracle_only,
        in_exported_method=[
            site
            for site in oracle_only
            if _inside_any(site, by_basename.get(site.file.rsplit("/", 1)[-1], []))
        ],
        wadi_only=[site for position, site in enumerate(distinct) if position not in paired],
        library_copies=copies,
    )


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


def to_json(result: Reconciliation) -> dict[str, Any]:
    return {
        "totals": result.totals(),
        "agree": [
            {"oracle": asdict(a.oracle), "wadi": asdict(a.wadi), "by_span": a.by_span}
            for a in result.agree
        ],
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
    parser.add_argument("--json", type=Path, help="write the three lists and the totals here")
    args = parser.parse_args(argv)

    files = export_files(args.exports)
    if not files:
        parser.error(f"no export JSON in {' '.join(map(str, args.exports))}")
    sites, spans = load_exports(files)
    result = reconcile(load_sites(args.oracle), sites, spans)
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
