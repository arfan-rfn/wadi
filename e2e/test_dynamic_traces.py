"""§5.2.8 M4: dynamic trace inclusion — executed reality is a subset of the graph.

The construct-matrix fixture runs as a real Spring Boot service under the
JaCoCo agent; every endpoint is driven over HTTP through both branch outcomes;
the recorded coverage is then diffed against a fresh wadi analysis of the same
source (real Joern container → export → assembler). The claim proven: every
line the JVM actually executed inside a handler method maps to an ICFG node,
and every branch the JVM took both ways sits on a node the graph renders as
branching. This is the one layer that checks the graph against reality rather
than against another model of it (the recorded reason it was not deferred).

Fixture-scoped by design; the oracle (M3) and always-on invariants (M2) carry
the load on arbitrary repos. Skips without docker/mvn/java.
"""

import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
from e2e_support import make_fixture_repo, requires_joern_image

from wadi_joern_client import JoernClient, ServiceExport
from wadi_worker.assembler import Assembler

pytestmark = [
    pytest.mark.integration,
    requires_joern_image,
    pytest.mark.skipif(
        shutil.which("mvn") is None or shutil.which("java") is None,
        reason="mvn + java required for the JaCoCo dynamic layer (§5.2.8 M4)",
    ),
]

JACOCO_VERSION = "0.8.12"
FIXTURE = (
    Path(__file__).resolve().parents[1] / "joern-platform" / "fixtures" / "control-flow-matrix"
)

# Every endpoint, driven through BOTH outcomes of its branches where the
# construct allows it (loops run 0 and N iterations, switches hit each arm).
DRIVE = [
    "/cond/if/5",
    "/cond/if/-5",
    "/cond/if-else/2",
    "/cond/if-else/3",
    "/cond/else-if/-1",
    "/cond/else-if/0",
    "/cond/else-if/5",
    "/cond/else-if/50",
    "/cond/ternary/-1",
    "/cond/ternary/1",
    "/cond/short-circuit/3",
    "/cond/short-circuit/-1",
    "/cond/short-circuit/50",
    "/cond/sink-in-condition/1",
    "/switch/classic/0",
    "/switch/classic/1",
    "/switch/classic/9",
    "/switch/fallthrough/2",
    "/switch/fallthrough/1",
    "/switch/fallthrough/9",
    "/switch/string/start",
    "/switch/string/stop",
    "/switch/string/other",
    "/switch/enum/SMALL",
    "/switch/enum/MEDIUM",
    "/switch/enum/LARGE",
    "/switch/arrow/0",
    "/switch/arrow/2",
    "/switch/arrow/9",
    "/switch/yield/0",
    "/switch/yield/5",
    "/switch/yield/50",
    "/loop/for/0",
    "/loop/for/4",
    "/loop/foreach/2",
    "/loop/while/0",
    "/loop/while/6",
    "/loop/do-while/0",
    "/loop/do-while/1234",
    "/loop/nested/0",
    "/loop/nested/3",
    "/loop/labeled/2",
    "/loop/labeled/8",
    "/loop/self/3",
    "/loop/stream/2",
    "/except/try-catch/12",
    "/except/try-catch/abc",
    "/except/multi-catch/5",
    "/except/multi-catch/0",
    "/except/finally/1",
    "/except/finally/-1",
    "/except/try-with-resources/hello",
    "/except/throw/5",
    "/except/throw/-5",
    "/except/sink-in-throw/1",
    "/except/sink-in-throw/-1",
    "/misc/synchronized/2",
    "/misc/multi-return/0",
    "/misc/multi-return/-3",
    "/misc/multi-return/7",
    "/misc/empty",
]

# Intra-method edge kinds that represent branch OUTCOMES at a node (call/return
# edges into inlined callees are interprocedural plumbing, not outcomes).
_OUTCOME_KINDS = {"flow", "true", "false", "case", "default", "fallthrough", "exception"}


def _attribution_artifact(source_line: str) -> bool:
    """§5.2.8 M4: lines JaCoCo attributes machinery to that hold no source
    statement — classified structurally from the source text, never a
    hand-kept line list. Loop-closing braces (jump machinery), fluent-chain
    continuations (executed across lines javasrc2cpg places on the chain's
    first line; lambda bodies run as their own methods), and `synchronized`
    headers (the construct is recorded non-modelled)."""
    stripped = source_line.strip()
    return (
        stripped == ""
        or all(ch in "}){;]" for ch in stripped)
        or stripped.startswith(".")
        or stripped.startswith("synchronized")
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _mvn(args: list[str], cwd: Path) -> None:
    subprocess.run(["mvn", "-q", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def executed_coverage(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, list[tuple[int, int, int, int]]]:
    """Run the fixture under JaCoCo, drive every endpoint, return per-file
    line coverage: {relative source path: [(line, ci, cb, mb)]}."""
    workdir = tmp_path_factory.mktemp("matrix-dyn")
    app = workdir / "app"
    shutil.copytree(FIXTURE, app, ignore=shutil.ignore_patterns("expected", "target"))
    _mvn(["package", "-DskipTests"], app)
    jacoco = workdir / "jacoco"
    _mvn(
        [
            "dependency:copy",
            f"-Dartifact=org.jacoco:org.jacoco.agent:{JACOCO_VERSION}:jar:runtime",
            f"-DoutputDirectory={jacoco}",
        ],
        app,
    )
    _mvn(
        [
            "dependency:copy",
            f"-Dartifact=org.jacoco:org.jacoco.cli:{JACOCO_VERSION}:jar:nodeps",
            f"-DoutputDirectory={jacoco}",
        ],
        app,
    )
    agent = jacoco / f"org.jacoco.agent-{JACOCO_VERSION}-runtime.jar"
    cli = jacoco / f"org.jacoco.cli-{JACOCO_VERSION}-nodeps.jar"
    exec_file = workdir / "jacoco.exec"
    jar = next(app.glob("target/control-flow-matrix-*.jar"))

    port = _free_port()
    proc = subprocess.Popen(
        [
            "java",
            f"-javaagent:{agent}=destfile={exec_file}",
            "-jar",
            str(jar),
            f"--server.port={port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 120
        with httpx.Client(timeout=5.0) as client:
            while True:
                try:
                    if client.get(f"{base}/misc/empty").status_code < 500:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("matrix fixture service never became ready")
                time.sleep(1)
            unexpected: list[str] = []
            for path in DRIVE:
                status = client.get(f"{base}{path}").status_code
                # /except/throw with n<0 answers 500 by design (it throws).
                if status >= 400 and path != "/except/throw/-5":
                    unexpected.append(f"{path} -> {status}")
            if unexpected:
                raise RuntimeError(f"drive requests failed (fixture/service bug): {unexpected}")
    finally:
        proc.terminate()
        proc.wait(timeout=30)

    report = workdir / "report.xml"
    subprocess.run(
        [
            "java",
            "-jar",
            str(cli),
            "report",
            str(exec_file),
            "--classfiles",
            str(app / "target" / "classes"),
            "--xml",
            str(report),
        ],
        check=True,
        capture_output=True,
    )

    coverage: dict[str, list[tuple[int, int, int, int]]] = {}
    root = ET.fromstring(report.read_text())
    for package in root.iter("package"):
        for sourcefile in package.iter("sourcefile"):
            rel = f"src/main/java/{package.get('name')}/{sourcefile.get('name')}"
            coverage[rel] = [
                (
                    int(line.get("nr", "0")),
                    int(line.get("ci", "0")),
                    int(line.get("cb", "0")),
                    int(line.get("mb", "0")),
                )
                for line in sourcefile.iter("line")
            ]
    return coverage


@pytest.fixture(scope="module")
def assembled_icfgs(shared_dir: Path, joern_url: str):
    """A fresh wadi analysis of the same fixture source: real Joern container
    → export 2.5.0 → assembler → ICFGs."""
    repo = make_fixture_repo(FIXTURE, shared_dir)
    export_dir = shared_dir / "matrix-dyn-export"
    client = JoernClient(joern_url, request_timeout=600)
    try:
        client.import_code(str(repo), "matrix-dyn")
        client.run_wadi_pipeline(str(export_dir))
    finally:
        client.close()
    export = ServiceExport.model_validate_json((export_dir / "export.json").read_bytes())
    return Assembler(snapshot_id="snap-dyn", service_id="svc_matrix").assemble(export)


def test_every_executed_line_exists_in_the_graph(executed_coverage, assembled_icfgs) -> None:
    """Trace inclusion (§5.2.8 M4): executed handler lines ⊆ ICFG node extents.

    Scoped to lines inside methods the graph claims to represent (ICFG method
    intervals) — exactly where a silently deleted statement (the pre-M1
    catch/finally/arrow-switch class) would hide.
    """
    node_lines: dict[str, set[int]] = {}
    method_lines: dict[str, set[int]] = {}
    branchy_lines: dict[str, set[int]] = {}
    for icfg in assembled_icfgs.icfgs:
        out_degree: dict[str, int] = {}
        for edge in icfg.edges:
            if edge.kind.value in _OUTCOME_KINDS:
                out_degree[edge.source] = out_degree.get(edge.source, 0) + 1
        by_id = {node.id: node for node in icfg.nodes}
        for node in icfg.nodes:
            span = set(range(node.anchor.start_line, node.anchor.end_line + 1))
            if node.kind.value == "entry":
                method_lines.setdefault(node.anchor.file, set())
            node_lines.setdefault(node.anchor.file, set()).update(span)
            renders_branching = (
                node.condition is not None
                or out_degree.get(node.id, 0) >= 2
                or "?" in node.source_text  # ternary: expression-level by design
            )
            if renders_branching:
                branchy_lines.setdefault(node.anchor.file, set()).update(span)
        # Method intervals: entry node line .. max node line of that method.
        for node in icfg.nodes:
            if node.kind.value == "entry":
                own = [
                    n
                    for n in by_id.values()
                    if n.method.id == node.method.id and n.anchor.file == node.anchor.file
                ]
                lo = min(n.anchor.start_line for n in own)
                hi = max(n.anchor.end_line for n in own)
                method_lines.setdefault(node.anchor.file, set()).update(range(lo, hi + 1))

    missing_lines: list[str] = []
    missing_branches: list[str] = []
    checked_lines = 0
    checked_branches = 0
    for rel, lines in executed_coverage.items():
        if not rel.endswith("Controller.java"):
            continue
        source_lines = (FIXTURE / rel).read_text().splitlines()
        graph_file = next((f for f in node_lines if f.endswith(rel)), None)
        assert graph_file is not None, f"no ICFG nodes at all for {rel}"
        in_method = method_lines.get(graph_file, set())
        covered_by_nodes = node_lines[graph_file]
        branchy = branchy_lines.get(graph_file, set())
        for line, ci, cb, mb in lines:
            if line not in in_method:
                continue  # class-level boilerplate (enum members, field decls of unreached types)
            if ci > 0:
                checked_lines += 1
                if line not in covered_by_nodes and not _attribution_artifact(
                    source_lines[line - 1] if line <= len(source_lines) else ""
                ):
                    missing_lines.append(f"{rel}:{line}")
            if cb >= 2 and mb == 0:
                checked_branches += 1
                # The artifact classes apply here too: a `.filter(x -> …)`
                # continuation line branches inside its own <lambda> method.
                if line not in branchy and not _attribution_artifact(
                    source_lines[line - 1] if line <= len(source_lines) else ""
                ):
                    missing_branches.append(f"{rel}:{line}")

    assert checked_lines > 100, "the drive list barely executed anything — harness bug"
    assert not missing_lines, (
        f"executed lines absent from the graph (deleted-statement class): {missing_lines}"
    )
    assert not missing_branches, (
        f"both branch outcomes executed but the graph renders no branching: {missing_branches}"
    )
