# Release 1b, the tie-break probe (2026-11-24)

Release 1b's plan sizes the node tie-break (track P3) from this probe and runs it before the
release's decision record merges. The plan asks whether Joern's node ids and the export's order
repeat across runs and machines, and whether the proposed tie value repeats. It also asks how
often two nodes that meet at a sort site share one tie value, which same-line groups would change
order, how many nodes have no file or no parent, and whether nodes in Lombok files carry a column.

## Method

The probe code is on branch `probe/p3-tie-break` at `8a60c36`. The branch is never merged.

- `TieProbe` (Scala, test scope) builds each service's CPG with the frontend configuration of
  `WadiPipeline.runFromSource`: javasrc2cpg, delombok `types-only`, the worker's exclude regex,
  and the default overlays. It then runs `WadiPipeline.run`, which is the DI pass, the packs and
  the real export. For every node id the export names, it records the node's label, its kind and
  sequence number (a Joern id is the kind shifted left by 32 bits plus the sequence number), its
  file, line, column and `order`, and its AST path, the `order` values from the root down.
- The driver (`probe/p3_tie_probe.py`) discovers and stages services with the worker's own
  `discover_system_services` and `stage_parse_root`, so library staging is the same as in an
  analysis. Each run is one fresh JVM that analyzes every service in turn, as the Joern server of
  a stack does.
- The tie value is the plan's `(file name, kind rank, ast_path)`. The kind rank is the kind half
  of the id.
- Inputs: the three pinned corpora, `train-ticket-aitest` at `a84716f`, yas at `2b09247` and
  piggymetrics at `6bb2cf9`, which give 52 services, 15 of them with staged libraries. Also the 12
  fixture services that discovery finds under `joern-platform/fixtures`. `restclient-yas-mini`
  yields no service.

| Run | Machine | Processors | Heap | JDK | Corpora | Fixtures |
|---|---|---|---|---|---|---|
| Mac A | the owner's Mac, macOS arm64 | 8 | 5 GB | 21.0.13 | 321 s | 62 s |
| Mac B | the same Mac, a new JVM | 2 (`-XX:ActiveProcessorCount=2`) | 5 GB | 21.0.13 | 330 s | 63 s |
| Mac C | the same Mac, a new JVM, with the enclosing type's file recorded | 4 | 5 GB | 21.0.13 | 320 s | 69 s |
| Runner | GitHub-hosted `ubuntu-latest`, Linux amd64, run 45464403723 | 4 | 10 GB | 21.0.13 | 422 s | 78 s |

No service failed in any run.

## Results

| Question | Answer |
|---|---|
| Do node ids repeat in separate JVMs on one machine? | Yes. Mac A, Mac B and Mac C give byte-identical exports for 52 of 52 corpus services and 12 of 12 fixtures. |
| Do node ids repeat on two machines? | Yes. Mac A and the runner give byte-identical exports for 52 of 52 and 12 of 12. |
| Does export order repeat? | Yes. The exports are byte-identical, so every list is in the same order. |
| Are tie values equal across runs? | Yes. In every comparison the tie value of each id, taken in export order, is equal. |
| Pairs of distinct nodes that meet at a sort site and share one tie | 0. Several rows of one node (a call that emits several patterns or URL values) are not counted, because they are one node. |
| Same-line groups whose order the tie would change | Flow-graph nodes: 21 of 1,159 groups in the corpora and 2 of 61 in the fixtures, all of one shape (below). Security rules: 0 of 2 in the corpora and 1 of 3 in the fixtures. |
| Nodes with no file | 418 of 23,193 exported nodes in the corpora and 7 of 1,672 in the fixtures. All are static initializers and the calls inside them (below). |
| Nodes with no AST parent | 0. |
| Do nodes in Lombok files carry a column? | Mostly. 3,306 of 3,376 exported nodes in files that import Lombok carry one, and 22,397 of 23,193 exported nodes overall. A column is missing on 3.4% of nodes, and `order` is on every node. |

### Static initializers have no file

javasrc2cpg gives a class's static initializer, `<clinit>`, the filename `<empty>`. The exporter
reports such a method's file as `<empty>`, and so does every call inside it. In the corpora that
is 193 methods and 225 calls. Their AST paths start at the type, so the initializers of two
classes can have equal paths. 116 exported nodes share a tie value with another node this way,
across 16 services, for example the `<clinit>` methods of `RouteController` and `UserController`
in `ts-route-service`. None of them meets another in a same-line group of a sort site.

Taking the file from the enclosing type declaration when a method's filename is `<empty>` gives
every one of those 418 nodes a file, and then no two exported nodes share a tie value (run Mac C).

### The one shape that changes order

All 23 flow-graph groups that would change order are a statement that assigns an anonymous class,
such as `UserDetails userDetails = new UserDetails() { ... }` (`ts-admin-service`, line 38).
Joern creates the constructor call before the assignment, so its id is lower, but in the AST the
assignment comes first. The tie puts the assignment first, which is source order. No other shape
changes.

### The one security-rule group that changes order

In the `spring-auth-matrix` fixture, rules from `StaticImportPrefixConfig.java` and
`Ss6ShapesConfig.java` both sit on line 59 of their files. Today the higher id comes first. The
plan's key orders them by file name. They belong to two chains, and the worker groups rules by
chain before it applies first-match-wins (`services/extraction-worker/src/wadi_worker/auth_merge.py:765`),
so no authorization claim changes. No such group exists in the corpora.

## What this decides

The plan's rule is: "If ids and order repeat on every corpus, in both JVMs and on both machines,
P3 shrinks to what the base migration record asks." They repeat, and the tie values repeat too, so
the branch where the tie-break design is wrong does not apply.

- P3 is the smaller track: `ast_path` in the exporter and in the export model, the export version
  and the new fixture. The sort sites stay as they are, and the determinism row watches them. A
  site is changed only when the gate or a later Joern upgrade shows it differ.
- P3 takes two and a half days, and the release estimate is 35 days of work.
- If a sort site is changed later, its tie takes the file from the enclosing type for a method
  whose filename is `<empty>`.

## Limits

- The probe ran `runFromSource` in standalone JVMs, not the Joern server of the `wadi-joern`
  image. Both use Joern 4.0.593 and the same frontend configuration, and each run analyzed all
  services in one JVM. The determinism gate (track E9) runs the real stack.
- Both machines ran JDK 21.0.13. A different JDK is not covered.
- The counts of groups that would change order cover the lists that the export carries with a
  node id and a line: flow-graph nodes, security rules and unreachable sinks. The other sort
  sites (sinks, entity facts, the slicer's candidates) and the method list, which is in closure
  order, are covered by byte equality only.
- The runner ran once.

## Files

- `release-1b-probe/compare-corpora-mac.json` and `compare-fixtures-mac.json`: Mac A against Mac B.
- `release-1b-probe/compare-corpora-mac-runner.json` and `compare-fixtures-mac-runner.json`: Mac A
  against the runner.
- `release-1b-probe/compare-corpora-mac-c.json` and `compare-fixtures-mac-c.json`: Mac C against Mac A. Only these two
  hold valid counts for the type file, because only Mac C recorded it.

To repeat a run, check out the probe branch and run, from the repository root:

```
cd joern-platform && sbt -batch "Test/compile" "export Test/fullClasspath" | tail -1 > /tmp/cp.txt && cd ..
uv run python probe/p3_tie_probe.py prepare --name yas --checkout <yas checkout> --work <dir>/work --manifest <dir>/m.json
uv run python probe/p3_tie_probe.py run --manifest <dir>/m.json --out <dir>/a --classpath /tmp/cp.txt
uv run python probe/p3_tie_probe.py run --manifest <dir>/m.json --out <dir>/b --classpath /tmp/cp.txt --processors 2
uv run python probe/p3_tie_probe.py compare --manifest <dir>/m.json --a <dir>/a --b <dir>/b
```
