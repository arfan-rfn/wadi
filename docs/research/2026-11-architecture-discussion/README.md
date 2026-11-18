# Architecture discussion of November 2026: research and record

**What this folder is.** The source material of a design discussion that ran on 2026-11-16 and
2026-11-17 against wadi 0.9.0 (commit `f838045`). Three plan documents in `docs/` hold its
results:

- `target-architecture-plan.md`: many sources, one map
- `bundle-import-and-hub-plan.md`: export, import and the hub
- `identity-and-access-plan.md`: test identities, the credential broker and the access prober

Those documents cite this folder as "report NN" and "item NNN". The architecture page the
discussion produced is `docs/designs/target-architecture-page.html`.

**What this folder is not.** It is not a decision record and not a statement of the design. The
reports are unedited, and the record contains answers that later answers replaced.

## Research reports

Each report was written by a research agent under a neutral brief. Reports 04 and 09 are audits of
this repository. The others are outside research. Each report says how it checked each source:
opened, abstract only, recalled from memory, preprint or vendor claim. Most outside pages came
through a fetch tool that returns an extract, so a quoted phrase is as that tool returned it.
Nobody opened the outside sources a second time.

| Report | Subject | File | Used by |
|---|---|---|---|
| 01 | Limits of static analysis | `report-01-static-analysis-limits.md` | `target-architecture-plan.md` |
| 02 | Evidence on models against static analysis | `report-02-models-against-static-analysis.md` | `target-architecture-plan.md` |
| 03 | Code context for coding agents | `report-03-code-context-for-agents.md` | `target-architecture-plan.md` |
| 04 | Audit: where wadi assumes code is the only source | `report-04-audit-single-source-assumptions.md` | `target-architecture-plan.md` |
| 05 | Reading Kubernetes, Helm and nginx correctly | `report-05-reading-kubernetes-helm-nginx.md` | `target-architecture-plan.md` |
| 06 | Inventory of non-code sources of truth | `report-06-inventory-non-code-sources.md` | `target-architecture-plan.md` |
| 07 | Runtime evidence and join keys | `report-07-runtime-evidence-and-join-keys.md` | `target-architecture-plan.md` |
| 08 | How other systems hold facts from several sources | `report-08-multi-source-evidence-prior-art.md` | `target-architecture-plan.md`, `bundle-import-and-hub-plan.md` |
| 09 | Audit: what wadi's auth extraction does today | `report-09-audit-auth-extraction.md` | `identity-and-access-plan.md` |
| 10 | Tools that detect authorization flaws | `report-10-tools-that-detect-authorization-flaws.md` | `identity-and-access-plan.md` |
| 11 | Academic research on authorization analysis | `report-11-academic-research-on-authorization-analysis.md` | `identity-and-access-plan.md` |
| 12 | Auth outside code and across services | `report-12-auth-outside-code-and-across-services.md` | `identity-and-access-plan.md` |
| 13 | How frameworks and policy engines declare auth | `report-13-how-frameworks-and-engines-declare-auth.md` | `identity-and-access-plan.md` |
| 14 | Credentials for automated API tests | `report-14-credentials-for-automated-api-tests.md` | `identity-and-access-plan.md` |
| 15 | Asking frameworks for auth decisions | `report-15-asking-frameworks-for-auth-decisions.md` | `identity-and-access-plan.md` |

## Record of the discussion

`discussion-record.md` holds the owner's questions and the answers, numbered as the plan documents
cite them. Item 035 is a review the owner pasted in.

## Corrections that apply to the record

- The MCP server has nine tools. One answer says eight.
- The first answer on authentication and authorization (item 080) was replaced by items 083, 088
  and 092, after the owner said it was biased toward the current implementation.
- The reader of trace files is the trace importer, marked later. Earlier answers call it the
  runtime importer.
- The owner decided on 2026-11-17 that image size and the 10 GB memory limit stay as they are
  during the proof of concept. The footprint suggestions in the record are not planned work.
- The current build order is the eleven-step list in `target-architecture-plan.md`. Shorter
  orders in earlier answers are replaced.
- The bundle plan corrected two statements of item 077 against the code. Its section 8.2 has the
  details.
