// Accounting fixtures that are valid 1.27.0 accounting, and the check that
// says so (review C9).
//
// The generated types cannot express the contract's invariants: a dict is
// `{ [k: string]: number }`, so `accesses_by_operation: {}` type-checks, and a
// cast let the tests carry accounting the API can never send. The derivations
// sum these numbers onto the page, so a fixture whose buckets do not add up
// pins totals that cannot occur. `accountingViolations` restates the two
// validators on `EntityAccessAccounting` in
// `libs/wadi-contracts/src/wadi_contracts/entity_access.py`
// (`_every_site_is_accounted_for`, `_counts_agree_with_the_partitions`), and
// entity-matrix.test.ts runs it over every accounting fixture.
import type {
  EntityAccessAccounting,
  EntityAccessBasis,
  EntityGateFlagState,
  EntityOperation,
} from "@/lib/generated/entity_usage.schema"

const OPERATIONS: EntityOperation[] = [
  "create",
  "read",
  "update",
  "delete",
  "create-or-update",
  "unknown",
]
const BASES: EntityAccessBasis[] = [
  "method-name",
  "query-text",
  "argument-origin",
  "existence-guard",
]

/** The four flags as the worker records them when none has been scored. */
export const SHIPPED_GATE_FLAGS: EntityGateFlagState[] = (
  ["argument-origin", "existence-guard"] as const
).flatMap((basis) =>
  (["create", "update"] as const).map((operation) => ({
    basis,
    operation,
    enabled: false,
    scored_rules_version: null,
  }))
)

/**
 * 20 calls: 15 in some endpoint flow and 5 in none; by outcome, 1 with a body
 * in the project, 2 entity undetermined, 3 verb unknown, 4 create-or-update
 * and 10 bound. The bases cover the 20 non-flush sites, and the 21 accesses
 * include at least 4 create-or-update and 3 unknown ones.
 */
export const SYNTHETIC_ACCOUNTING: EntityAccessAccounting = {
  call_sites: 20,
  in_endpoint_flow: 15,
  in_no_endpoint_flow: 5,
  flush: 0,
  implemented_in_project: 1,
  entity_undetermined: 2,
  unknown_operation: 3,
  create_or_update: 4,
  bound: 10,
  accesses_by_operation: {
    create: 0,
    read: 9,
    update: 0,
    delete: 2,
    "create-or-update": 4,
    unknown: 6,
  } satisfies Record<EntityOperation, number>,
  sites_by_basis: {
    "method-name": 13,
    "query-text": 3,
    "argument-origin": 4,
    "existence-guard": 0,
  } satisfies Record<EntityAccessBasis, number>,
  rules_version: "r1",
  gate_flags: SHIPPED_GATE_FLAGS,
}

function keyViolation(
  name: string,
  counts: Record<string, number>,
  vocabulary: readonly string[]
): string[] {
  const keys = Object.keys(counts).sort()
  return keys.join() === [...vocabulary].sort().join()
    ? []
    : [`${name} keys ${keys.join(",")} are not ${vocabulary.join(",")}`]
}

/** Every way `a` breaks the contract's accounting validators; [] when valid. */
export function accountingViolations(a: EntityAccessAccounting): string[] {
  const problems: string[] = []
  if (a.in_endpoint_flow + a.in_no_endpoint_flow !== a.call_sites)
    problems.push("the flow partition does not sum to call_sites")
  const outcomes =
    a.flush +
    a.implemented_in_project +
    a.entity_undetermined +
    a.unknown_operation +
    a.create_or_update +
    a.bound
  if (outcomes !== a.call_sites)
    problems.push(`the outcome partition sums to ${outcomes}`)
  problems.push(
    ...keyViolation(
      "accesses_by_operation",
      a.accesses_by_operation,
      OPERATIONS
    ),
    ...keyViolation("sites_by_basis", a.sites_by_basis, BASES)
  )
  const sum = (counts: Record<string, number>) =>
    Object.values(counts).reduce((total, n) => total + n, 0)
  const sites = sum(a.sites_by_basis)
  if (sites !== a.call_sites - a.flush)
    problems.push(`sites_by_basis sums to ${sites}, not call_sites - flush`)
  if (sum(a.accesses_by_operation) < sites)
    problems.push("fewer accesses than the sites they describe")
  if ((a.accesses_by_operation["create-or-update"] ?? 0) < a.create_or_update)
    problems.push("fewer create-or-update accesses than sites in that bucket")
  if ((a.accesses_by_operation.unknown ?? 0) < a.unknown_operation)
    problems.push("fewer unknown accesses than sites in that bucket")
  return problems
}
