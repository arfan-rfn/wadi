# Constraints

Last reviewed: 2026-11-14 by the repository owner, at the start of Phase 2.10.

This file records the bar a change must meet before it merges. It codifies the gates
`.github/workflows/ci.yml` already enforces and adds no new tool. The `Checked by` column is
the canonical command. If a script or Makefile target drifts from it, this file wins.

## Floor (always enforced, no setup required)

- No new suppression comments: `# type: ignore`, `# pyright: ignore`, `# noqa`,
  `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `@nowarn`.
- No unimplemented stubs: `raise NotImplementedError`, `throw new Error("Not implemented")`,
  `???` in Scala, an empty `except: pass` or `catch {}`.
- No skipped or deleted tests without a reason in the commit message: `pytest.mark.skip`,
  `.skip(`, `ignore(` in ScalaTest. A test that skips on a missing prerequisite and says which
  one (`petstore-system export not present`) is the existing pattern and is allowed.
- No secrets in source.
- No assertion removed from a test that stays.
- This file does not get weakened to make a change pass.

## Enforced with numbers

Every row blocks a merge. Zero means zero: there is no tolerance band on any of them.

| Dimension | Rule | Checked by | Runs at |
|---|---|---|---|
| Python lint | Zero findings, zero unformatted files (Markdown Python fences included) | `uv run ruff check . && uv run ruff format --check .` | task end, CI |
| Python types | Zero errors, zero warnings, pyright strict, workspace-wide | `uv run pyright` | task end, CI |
| Python tests | All pass, unit and Mongo integration (Docker) | `uv run pytest -q` | task end (unit: `uv run pytest -m "not integration"`), CI |
| Contract schemas | `schemas/` matches `wadi-contracts` | `make schema && git diff --exit-code schemas/ frontend/lib/generated/` | task end after any contracts change, CI |
| CLI compose copy | The CLI's embedded compose matches `infra/` | `make sync-compose && git diff --exit-code cli/src/wadi_cli/resources/` | task end after any compose change, CI |
| Licences | No GPL dependency (LGPL allowed) | the `License scan` step in `ci.yml` | CI |
| Scala | Conformance tests pass, compiled with `-Werror` | `cd joern-platform && mvn -q -f fixtures/control-flow-matrix/pom.xml compile && sbt -batch test` | task end for Scala changes, CI |
| Scala jar | The jar shipped in the wadi-joern image builds | `cd joern-platform && sbt -batch assembly` | CI |
| Frontend | ESLint, Prettier, `tsc --noEmit`, `next build`, vitest, in CI's order | `make verify-frontend` | task end for frontend changes, CI |
| Whole stack | The conformance e2e passes against the real Joern image | `make joern-image && make e2e` | release checkpoint, CI |

The cross-language golden tests (`test_real_export*.py`, `test_real_auth_matrix.py`,
`test_real_crud_matrix.py`, and `libs/wadi-testing/tests/test_reconcile_repository_sites.py`)
skip until `sbt test` has written their exports. A Scala or export change is not verified until
they have run against a fresh `sbt test`, not skipped. In CI that skip is a failure: the step
"Real-export goldens ran, none skipped for a missing export" in `ci.yml` reruns every test file
whose skip reason says "export not present" and fails the Python job on any skip.

## Measured, not yet enforced

None recorded. Coverage, dependency scanning and secret scanning were offered on
2026-11-14 and not chosen.

## Exceptions

None.

## Where the bar is external

Most rows are project checks (our ruff and pyright config, our tests). Two are external
opinions the agent cannot argue with: the licence scan reads each dependency's declared
licence, and `make e2e` runs the real, pinned Joern rather than a test double.
