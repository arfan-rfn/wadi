# Entity access measurements (§5.2.17)

This directory holds the evidence behind every entity-access number that
`docs/architecture.md` §5.2.17 and `CLAUDE.md` publish. It exists because the
first round of evidence lived under `plan/`, which git excludes, so nobody could
rerun it from the repository (review D5). Each measurement below has a script
in `libs/wadi-testing/src/wadi_testing/measure/` and a Makefile target or a
module command. A run writes its working files outside the repository and
commits a summary here.

The corpus is never committed. Derived results are: the summary, and the small
files a reader needs to rescore the hand check.

## The three measurements

**1. The repository call-site oracle.** `repository_oracle` reads Java source
and never an export, so it can find a repository call that wadi did not tag
(C4). For each site it records where the call is, the repository it calls, the
entity the repository's type argument names, and its own reading of the
operation from the method name and declaration. Its rules and blind spots are in
the module docstring.

**2. The reconciliation.** `reconcile_repository_sites` pairs oracle sites with
wadi's db sinks one site at a time and lists three groups: sites both found,
sites only the oracle found, and sites only wadi found. Each site both found is
then compared twice more (review D6):

- on entity, against the type argument wadi bound in the export. An entity wadi
  left undetermined counts as withheld, never as agreement;
- on operation, against what the snapshot published on its ICFG nodes. The
  export carries no operation, because the worker decides it, so this needs the
  snapshot bundle. Two query readings are not compared on the verb, because the
  oracle does not read query text. A query on one side only is listed.

Every disagreement is listed with both sides, and each one has to be opened and
explained in the run's summary.

**3. The blind hand check.** `blind_sample draw` takes a seeded simple random
sample of the snapshot's endpoints and adds every endpoint wadi found hard (two
or more entities, or three or more call sites) as a second stratum. The reader
gets `blind.json`, which names each handler and nothing wadi concluded, and
labels each endpoint from the source alone. `blind_sample score` scores the
labels against `key.json`, which holds wadi's answers. The scoring rules are in
the module docstring. The report gives, per stratum, the endpoints in full
agreement, the pair counts (exact, less specific, withheld, over-claim, miss),
and a one-sided 95% Clopper-Pearson upper bound on the endpoint error rate. Only
the random stratum's bound speaks for the whole snapshot.

## Reproducing a run

The exports, the snapshot and the oracle must all come from the same corpus
commit, and the exports and the snapshot from the same wadi revision. Set these
first. `RUN` is a working directory outside the repository.

```sh
CORPUS=~/wadi-corpora/train-ticket-aitest
RUN=~/wadi-runs/2026-11-15-train-ticket
API=http://127.0.0.1:9234/api/v1
mkdir -p "$RUN"
git -C "$CORPUS" rev-parse HEAD > "$RUN/corpus-commit.txt"
git rev-parse HEAD > "$RUN/wadi-commit.txt"
```

Run the oracle on the corpus.

```sh
make measure-repository-sites SRC="$CORPUS" OUT="$RUN/oracle.json" > "$RUN/oracle.txt"
```

Store each service's export with the baseline harness. It names each file after
its service, which is how the reconciler pairs an export with the snapshot.

```sh
WADI_BASELINE_REPO="$CORPUS" WADI_BASELINE_EXPORT_DIR="$RUN/exports" \
    uv run pytest e2e/test_baseline_snapshot.py -q -s
```

Analyze the same corpus on the stack, then save the snapshot bundle and the
coverage report. `SNAP` is the snapshot id `wadi analyze` prints.

```sh
curl -sf "$API/snapshots/$SNAP/export" -o "$RUN/snapshot.ndjson"
curl -sf "$API/snapshots/$SNAP/coverage" -o "$RUN/coverage.json"
```

Reconcile.

```sh
uv run python -m wadi_testing.measure.reconcile_repository_sites \
    --oracle "$RUN/oracle.json" --exports "$RUN/exports" \
    --published "$RUN/snapshot.ndjson" --json "$RUN/reconciled.json" \
    > "$RUN/reconcile.txt"
```

Check that the exports and the snapshot paired. When wadi-only is 0, `agree`
minus `operation_unpublished` should equal `entity_coverage.in_endpoint_flow`
in `coverage.json`. A smaller number means some exports did not pair with the
snapshot. The reconciler prints every export that no published service is named
after.

Draw the blind sample. Choose the seed before drawing and record it; the run's
date as an integer (20261115) is the convention. N = 20 bounds the endpoint
error rate at 13.9% when no error is seen.

```sh
make blind-sample SNAPSHOT="$SNAP" SEED=20261115 N=20 CORPUS="$CORPUS" API="$API" \
    OUT="$RUN/blind"
```

Give the reader `$RUN/blind/blind.json` and read access to the corpus, and
nothing else: not `key.json`, not the stack, not a snapshot id. The reader
writes `$RUN/blind/labels.json` in the format `blind.json` states. Then score.

```sh
make blind-score KEY="$RUN/blind/key.json" LABELS="$RUN/blind/labels.json" \
    OUT="$RUN/blind/score.json" > "$RUN/blind/score.txt"
```

`blind-score` exits 1 while any drawn endpoint is unlabeled or a label names no
drawn endpoint.

## Files a run writes

| File | Written by | Committed |
|---|---|---|
| `corpus-commit.txt`, `wadi-commit.txt` | the setup commands | copied into the summary |
| `oracle.json`, `oracle.txt` | `measure-repository-sites` | no; sha256 in the summary |
| `exports/<service>.json` | the baseline harness | no; sha256 of each in the summary |
| `snapshot.ndjson`, `coverage.json` | the orchestrator | no; sha256 in the summary |
| `reconciled.json`, `reconcile.txt` | `reconcile_repository_sites` | no; totals and every disagreement in the summary |
| `blind/blind.json`, `blind/key.json` | `blind-sample` | yes, under `<date>-<corpus>/` |
| `blind/labels.json` | the reader | yes, under `<date>-<corpus>/` |
| `blind/score.json`, `blind/score.txt` | `blind-score` | yes, under `<date>-<corpus>/` |

The hand-check files are small and are what a second reader needs to rescore or
to label the same sample. The large files are reproducible from the commands
above at the recorded commits.

## Where a run's summary goes

Each run gets `docs/measurements/entity-access/<date>-<corpus>.md` (for example
`2026-11-15-train-ticket.md`), with its hand-check files in the directory of
the same name. Use this skeleton. The numbers stay empty until a run fills
them.

```markdown
# <corpus> at <corpus commit>, wadi <wadi commit>, <date>

Snapshot: <snapshot id>. Seed: <seed>. N: <N>. Reader: <who, and how they were
briefed>.

## Reconciliation

| Measure | Count |
|---|---|
| Oracle sites | |
| Wadi sites | |
| Agree on location | |
| Oracle only (in an exported method) | ( ) |
| Wadi only | |
| Entity: agree / disagree / withheld | / / |
| Operation: agree / disagree | / |
| Operation: one-sided query / both query / unpublished | / / |

Every entity disagreement, operation disagreement and one-sided query, with
what opening it showed:

| Site | Oracle | Wadi | Explanation |
|---|---|---|---|

Oracle-only sites: how many were opened, how they were chosen, and what each
was.

## Blind hand check

| Stratum | Endpoints | Full agreement | With an error | Error rate upper bound (95%) |
|---|---|---|---|---|
| Random | | | | |
| Hard | | | | |

| Pair verdict | Random | Hard |
|---|---|---|
| Exact | | |
| Less specific | | |
| Withheld | | |
| Over-claim | | |
| Miss | | |

Every endpoint with an error, and what opening it showed.

## Inputs

sha256 of `oracle.json`, each export, `snapshot.ndjson` and `coverage.json`.
```
