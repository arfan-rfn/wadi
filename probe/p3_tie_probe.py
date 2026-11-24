"""Release 1b P3 probe driver. Throwaway: lives on `probe/p3-tie-break`, never merged.

prepare  discover and stage services with the worker's own code, write a manifest
run      run TieProbe over a manifest in one fresh JVM
compare  compare two run directories and print the report as JSON
"""

from __future__ import annotations

import argparse
import functools
import itertools
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ID_KEYS = ("id", "method_id", "callee_id", "node_id", "call_id")


# --- prepare -----------------------------------------------------------------


def prepare(args: argparse.Namespace) -> None:
    from wadi_contracts.ids import normalize_repo_source, service_id
    from wadi_worker.boundary import discover_system_services
    from wadi_worker.pipeline import stage_parse_root

    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    systems: list[tuple[str, Path]] = []
    if args.fixtures:
        for d in sorted(Path(args.fixtures).iterdir()):
            if d.is_dir():
                systems.append((f"fixtures/{d.name}", d.resolve()))
    else:
        systems.append((args.name, Path(args.checkout).resolve()))

    manifest: list[dict[str, str]] = []
    for system_name, checkout in systems:
        normalized = normalize_repo_source(str(checkout))
        checkouts = {normalized: checkout}
        by_repo = discover_system_services(checkouts)
        workspace = work / "stage" / system_name.replace("/", "__")
        for service in by_repo.get(normalized, []):
            if service.kind == "library":
                continue
            svc_id = service_id(str(checkout), service.build_root)
            parse_root = stage_parse_root(workspace, checkout, checkouts, service, svc_id)
            manifest.append(
                {
                    "name": f"{system_name}/{service.name}",
                    "parse_root": str(parse_root),
                    "build_root": service.build_root,
                    "libraries": ",".join(service.library_roots),
                }
            )
    out = Path(args.manifest)
    out.write_text(json.dumps(manifest, indent=1))
    print(f"{len(manifest)} services -> {out}")


# --- run ---------------------------------------------------------------------


def run(args: argparse.Namespace) -> None:
    classpath = Path(args.classpath).read_text().strip()
    cmd = ["java", f"-Xmx{args.heap}"]
    if args.processors:
        cmd.append(f"-XX:ActiveProcessorCount={args.processors}")
    cmd += ["-cp", classpath, "wadi.probe.TieProbe", args.manifest, args.out]
    print(" ".join(cmd[:4]), "...", file=sys.stderr)
    subprocess.run(cmd, check=True)


# --- compare -----------------------------------------------------------------


def _load(run_dir: Path, name: str) -> tuple[Any, dict[str, Any]] | None:
    export_path = run_dir / name / "export.json"
    nodes_path = run_dir / name / "nodes.json"
    if not export_path.exists() or not nodes_path.exists():
        return None
    return json.loads(export_path.read_text()), json.loads(nodes_path.read_text())


def _id_sequence(value: Any, out: list[int]) -> None:
    if isinstance(value, dict):
        for key, v in value.items():
            if key in ID_KEYS and isinstance(v, int) and not isinstance(v, bool):
                out.append(v)
            else:
                _id_sequence(v, out)
    elif isinstance(value, list):
        for v in value:
            _id_sequence(v, out)


def _renumber(value: Any, mapping: dict[int, int]) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, v in value.items():
            if key in ID_KEYS and isinstance(v, int) and not isinstance(v, bool):
                out[key] = mapping.setdefault(v, len(mapping))
            else:
                out[key] = _renumber(v, mapping)
        return out
    if isinstance(value, list):
        return [_renumber(v, mapping) for v in value]
    return value


NO_FILE = ("<unknown>", "<empty>", "")


def _tie(node: dict[str, Any], file_key: str = "file") -> tuple[Any, ...]:
    # ujson writes a Long as a string, so the kind is parsed back to a number here.
    kind = int(node.get("kind", -1))
    return (node.get(file_key, node.get("file", "<unknown>")), kind, tuple(node.get("path", [])))


def _key_of(o: dict[str, Any]) -> tuple[int, int] | None:
    """(line, id) for an export row: `id`, `call_id` or `node_id`, and `line` or `anchor.line`."""
    ident = next((o[k] for k in ("id", "call_id", "node_id") if isinstance(o.get(k), int)), None)
    line = o.get("line")
    if not isinstance(line, int) and isinstance(o.get("anchor"), dict):
        line = o["anchor"].get("line")
    if ident is None or not isinstance(line, int):
        return None
    return line, ident


def _lists_with_ids(value: Any, path: str, out: list[tuple[str, list[dict[str, Any]]]]) -> None:
    """Every array of rows that carry a node id and a line: the export's id-ordered lists."""
    if isinstance(value, dict):
        for key, v in value.items():
            _lists_with_ids(v, f"{path}.{key}", out)
    elif isinstance(value, list):
        objs = [v for v in value if isinstance(v, dict)]
        if objs and len(objs) == len(value) and all(_key_of(o) is not None for o in objs):
            out.append((path, objs))
        for v in value:
            _lists_with_ids(v, f"{path}[]", out)


def _decl_cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """The plan's order for the (line, -id) sites: an earlier statement first, and inside one
    chain the inner call, whose AST path extends the outer call's, before the call that wraps it."""
    if a == b:
        return 0
    if len(a) > len(b) and a[: len(b)] == b:
        return -1
    if len(b) > len(a) and b[: len(a)] == a:
        return 1
    return -1 if a < b else 1


def _site_analysis(export: Any, nodes: dict[str, Any], file_key: str) -> dict[str, dict[str, int]]:
    lists: list[tuple[str, list[dict[str, Any]]]] = []
    _lists_with_ids(export, "", lists)
    sites: dict[str, Counter[str]] = defaultdict(Counter)

    def tie(ident: int) -> tuple[Any, ...]:
        return _tie(nodes.get(str(ident), {}), file_key)

    for path, objs in lists:
        site = sites[path]
        site["lists"] += 1
        keys = [_key_of(o) for o in objs]
        asc = [(line, ident) for line, ident in keys]  # type: ignore[misc]
        desc = [(line, -ident) for line, ident in keys]  # type: ignore[misc]
        if asc == sorted(asc):
            mode = "asc"
        elif desc == sorted(desc):
            mode = "desc"
        else:
            site["other_order"] += 1
            continue
        site[f"sorted_line_{'id' if mode == 'asc' else 'minus_id'}"] += 1
        by_line: dict[int, list[int]] = defaultdict(list)
        for line, ident in keys:  # type: ignore[misc]
            if ident not in by_line[line]:
                by_line[line].append(ident)  # rows of one node keep their own order
        for group in by_line.values():
            if len(group) < 2:
                continue
            site["same_line_groups"] += 1
            ties = [tie(i) for i in group]
            for a, b in itertools.combinations(ties, 2):
                if a == b:
                    site["distinct_node_pairs_sharing_tie"] += 1
            if mode == "asc":
                old = sorted(group)
                new = sorted(group, key=lambda i: (tie(i), i))
            else:
                old = sorted(group, key=lambda i: -i)
                new = sorted(
                    group,
                    key=functools.cmp_to_key(
                        lambda x, y: (tie(x)[0] > tie(y)[0]) - (tie(x)[0] < tie(y)[0])
                        or _decl_cmp(tie(x)[2], tie(y)[2])
                        or (x > y) - (x < y)
                    ),
                )
            if old != new:
                site["groups_new_order_differs"] += 1
    return {k: dict(v) for k, v in sites.items()}


def _lombok_files(parse_root: str) -> set[str]:
    root = Path(parse_root)
    found: set[str] = set()
    if not root.exists():
        return found
    for f in root.rglob("*.java"):
        try:
            if "import lombok" in f.read_text(errors="ignore"):
                found.add(str(f.relative_to(root)))
        except OSError:
            continue
    return found


def compare(args: argparse.Namespace) -> None:
    a_dir, b_dir = Path(args.a), Path(args.b)
    manifest = json.loads(Path(args.manifest).read_text())
    report: dict[str, Any] = {"a": str(a_dir), "b": str(b_dir), "services": {}}
    totals: Counter[str] = Counter()
    sites_total: dict[str, Counter[str]] = defaultdict(Counter)
    for entry in manifest:
        name = entry["name"]
        la, lb = _load(a_dir, name), _load(b_dir, name)
        if la is None or lb is None:
            report["services"][name] = {"missing": [x for x, l in (("a", la), ("b", lb)) if l is None]}
            totals["services_missing"] += 1
            continue
        (ea, na), (eb, nb) = la, lb
        ids_a: list[int] = []
        ids_b: list[int] = []
        _id_sequence(ea, ids_a)
        _id_sequence(eb, ids_b)
        raw_equal = ea == eb
        renumbered_equal = _renumber(ea, {}) == _renumber(eb, {})
        nodes_a, nodes_b = na["nodes"], nb["nodes"]
        ties_a = [_tie(nodes_a.get(str(i), {})) for i in ids_a]
        ties_b = [_tie(nodes_b.get(str(i), {})) for i in ids_b]
        distinct = {str(i) for i in ids_a}
        tie_counts = Counter(_tie(nodes_a[i]) for i in distinct if i in nodes_a)
        colliding_nodes = sum(c for c in tie_counts.values() if c > 1)
        via_type = Counter(_tie(nodes_a[i], "file_via_type") for i in distinct if i in nodes_a)
        colliding_via_type = sum(c for c in via_type.values() if c > 1)
        no_file = sum(1 for i in distinct if nodes_a.get(i, {}).get("file", "<unknown>") in NO_FILE)
        no_file_via_type = sum(
            1 for i in distinct if nodes_a.get(i, {}).get("file_via_type", "<unknown>") in NO_FILE
        )
        no_parent = sum(1 for i in distinct if not nodes_a.get(i, {}).get("parent", False))
        missing = sum(1 for i in distinct if nodes_a.get(i, {}).get("missing"))
        lombok = _lombok_files(entry["parse_root"])
        in_lombok = [nodes_a[i] for i in distinct if i in nodes_a and nodes_a[i].get("file") in lombok]
        svc = {
            "export_bytes_equal": raw_equal,
            "export_equal_after_renumbering_ids": renumbered_equal,
            "id_sequence_equal": ids_a == ids_b,
            "tie_sequence_equal": ties_a == ties_b,
            "cpg_node_count": [na.get("node_count"), nb.get("node_count")],
            "referenced_nodes": len(distinct),
            "nodes_sharing_a_tie": colliding_nodes,
            "nodes_sharing_a_tie_file_from_type": colliding_via_type,
            "nodes_without_file": no_file,
            "nodes_without_file_from_type": no_file_via_type,
            "nodes_without_parent": no_parent,
            "nodes_missing_from_cpg": missing,
            "lombok_files": len(lombok),
            "nodes_in_lombok_files": len(in_lombok),
            "nodes_in_lombok_files_with_column": sum(1 for n in in_lombok if "column" in n),
            "nodes_with_column": sum(1 for i in distinct if "column" in nodes_a.get(i, {})),
        }
        sites = _site_analysis(ea, nodes_a, "file")
        for site, counts in sites.items():
            sites_total[site].update(counts)
        report["services"][name] = svc
        totals["services"] += 1
        for key in ("export_bytes_equal", "export_equal_after_renumbering_ids", "id_sequence_equal", "tie_sequence_equal"):
            totals[key] += int(bool(svc[key]))
        for key in (
            "referenced_nodes",
            "nodes_sharing_a_tie",
            "nodes_sharing_a_tie_file_from_type",
            "nodes_without_file",
            "nodes_without_file_from_type",
            "nodes_without_parent",
            "nodes_missing_from_cpg",
            "nodes_in_lombok_files",
            "nodes_in_lombok_files_with_column",
            "nodes_with_column",
        ):
            totals[key] += svc[key]  # type: ignore[operator]
    report["totals"] = dict(totals)
    report["sites"] = {k: dict(v) for k, v in sorted(sites_total.items())}
    for side, d in (("a", a_dir), ("b", b_dir)):
        run_json = d / "run.json"
        if run_json.exists():
            meta = json.loads(run_json.read_text())
            meta.pop("services", None)
            report[f"{side}_run"] = meta
    print(json.dumps(report, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prepare")
    pp.add_argument("--name")
    pp.add_argument("--checkout")
    pp.add_argument("--fixtures")
    pp.add_argument("--work", required=True)
    pp.add_argument("--manifest", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--manifest", required=True)
    pr.add_argument("--out", required=True)
    pr.add_argument("--classpath", required=True)
    pr.add_argument("--heap", default="5g")
    pr.add_argument("--processors", type=int, default=0)
    pc = sub.add_parser("compare")
    pc.add_argument("--manifest", required=True)
    pc.add_argument("--a", required=True)
    pc.add_argument("--b", required=True)
    args = p.parse_args()
    {"prepare": prepare, "run": run, "compare": compare}[args.cmd](args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    main()
