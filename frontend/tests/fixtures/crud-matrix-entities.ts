// The crud-matrix fixture's `/entities` payload, as a 1.27.0 reader receives
// it, and the coverage section beside it (review C9). Typed by annotation, with
// no cast: a field the generated types do not accept fails `tsc`, and the Python
// contract (`EntityUsageView`, `EntityCoverageSection`) validated both before
// they were written here.
//
// Provenance. `entities` and the accounting are the `/entities` response the
// R1 build checkpoint captured from a live stack (snapshot snap_f7817a3c,
// contracts 1.26.0; the capture lives in the uncommitted `plan/evidence/R1/`),
// unchanged except for the two fields 1.27.0 added:
//
// - `status: "reporting"` on the one service, which carries accounting.
// - `call_sites` under each operation is now that operation's count. Where an
//   endpoint is listed under ONE operation of an entity, every one of its
//   sites on that entity performs it, so the 1.26.0 entity count is exact.
//   Where it is listed under several, R3 kept no payload with ICFG sites, so
//   the split was set by hand from the per-site goldens in
//   `services/extraction-worker/tests/test_real_crud_matrix.py`: for example
//   POST /crud/inherited-method-table reads Order at 5 sites, deletes it at 3
//   and saves it at 3 (golden 34), where 1.26.0 said 11 under each.
//
// The coverage section is summed from that accounting the way the stitcher's
// `build_entity_coverage` sums it. `gated_operations` was set by hand from the
// contract's rule, because all four gate flags in this run are off.
import type { EntityCoverageSection } from "@/lib/generated/coverage_report.schema"
import type { EntityUsageView } from "@/lib/generated/entity_usage.schema"

export const CRUD_MATRIX_ENTITIES: EntityUsageView = {
  snapshot_id: "snap_f7817a3c66a74239b4de8576ca4412bd",
  analyzed: true,
  endpoints_predating: 0,
  entities: [
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.billing.Account",
      name: "Account",
      data_model_id: "dm_47d338a8b044c8d6",
      storage_name: "billing_accounts",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_57a7bb1d5d7555d3",
              http_method: "GET",
              full_uri: "/crud/same-simple-name-two-packages",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.crm.Account",
      name: "Account",
      data_model_id: "dm_c2240eaf225b0e22",
      storage_name: null,
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_57a7bb1d5d7555d3",
              http_method: "GET",
              full_uri: "/crud/same-simple-name-two-packages",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.AuditEntry",
      name: "AuditEntry",
      data_model_id: "dm_c66c3fc8af064755",
      storage_name: null,
      declared_by: "repository-argument",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_307c74dd81a86d83",
              http_method: "GET",
              full_uri: "/crud/repository-only-entity",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Customer",
      name: "Customer",
      data_model_id: "dm_93c0c4314d1c5f13",
      storage_name: "customers",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_71f47a3023322fcd",
              http_method: "GET",
              full_uri: "/crud/query-named",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Invoice",
      name: "Invoice",
      data_model_id: "dm_79dec158b30ab680",
      storage_name: "invoices",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_b2f78b53f808ddab",
              http_method: "DELETE",
              full_uri: "/crud/query-delete-with-subquery",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_71f47a3023322fcd",
              http_method: "GET",
              full_uri: "/crud/query-named",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Issue",
      name: "Issue",
      data_model_id: "dm_6aabe20c53cdc755",
      storage_name: null,
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_517fe466fa8c55ef",
              http_method: "POST",
              full_uri: "/crud/base-interface-repository",
              call_sites: 2,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_71f47a3023322fcd",
              http_method: "GET",
              full_uri: "/crud/query-named",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Order",
      name: "Order",
      data_model_id: "dm_85a43d06e1576d16",
      storage_name: "orders",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_ae1588acd96b64d0",
              http_method: "GET",
              full_uri: "/crud/derived-count-exists",
              call_sites: 2,
            },
            {
              endpoint_id: "ep_041669503fbfb3ec",
              http_method: "GET",
              full_uri: "/crud/derived-find-by-status",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_6ba988c2e3bb9a91",
              http_method: "PUT",
              full_uri: "/crud/dirty-checking-setter",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_a7161648d79ccfcd",
              http_method: "GET",
              full_uri: "/crud/inherited-find-by-id",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_139e3e16700567c5",
              http_method: "POST",
              full_uri: "/crud/inherited-method-table",
              call_sites: 5,
            },
            {
              endpoint_id: "ep_2d74a0c097d830d3",
              http_method: "PUT",
              full_uri: "/crud/inherited-save-read-origin",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_da009ac1ea8d383b",
              http_method: "PUT",
              full_uri: "/crud/repository-default-method",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_1a73396fa35079da",
              http_method: "POST",
              full_uri: "/crud/save-guard-early-return",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_5b2a2c88476b02ad",
              http_method: "PUT",
              full_uri: "/crud/save-guard-found-arm",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_c50e5c1cb2f688c8",
              http_method: "POST",
              full_uri: "/crud/save-guard-not-found-arm",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_45a3331794528c0c",
              http_method: "PUT",
              full_uri: "/crud/save-parameter-callers-agree",
              call_sites: 2,
            },
            {
              endpoint_id: "ep_ed59a86b3d124f5a",
              http_method: "PUT",
              full_uri: "/crud/save-parameter-callers-disagree",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_9f8264d71f2d4632",
              http_method: "PUT",
              full_uri: "/crud/save-upsert-by-branch",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_0e96032ecb4f2f4a",
              http_method: "PUT",
              full_uri: "/crud/save-via-helper-wrapper",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_359255df0a62efef",
              http_method: "PUT",
              full_uri: "/crud/two-calls-one-statement",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [
            {
              endpoint_id: "ep_a3a5fc767ca05d9c",
              http_method: "PUT",
              full_uri: "/crud/delete-then-save",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_7b3e840230fdca82",
              http_method: "DELETE",
              full_uri: "/crud/derived-delete-by",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_6900c9c248dd1e15",
              http_method: "DELETE",
              full_uri: "/crud/inherited-delete",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_139e3e16700567c5",
              http_method: "POST",
              full_uri: "/crud/inherited-method-table",
              call_sites: 3,
            },
          ],
        },
        {
          operation: "create-or-update",
          endpoints: [
            {
              endpoint_id: "ep_a3a5fc767ca05d9c",
              http_method: "PUT",
              full_uri: "/crud/delete-then-save",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_139e3e16700567c5",
              http_method: "POST",
              full_uri: "/crud/inherited-method-table",
              call_sites: 3,
            },
            {
              endpoint_id: "ep_2d74a0c097d830d3",
              http_method: "PUT",
              full_uri: "/crud/inherited-save-read-origin",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_da009ac1ea8d383b",
              http_method: "PUT",
              full_uri: "/crud/repository-default-method",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_7f8c7eaabd8348bc",
              http_method: "POST",
              full_uri: "/crud/save-constructed-no-lookup",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_1a73396fa35079da",
              http_method: "POST",
              full_uri: "/crud/save-guard-early-return",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_5b2a2c88476b02ad",
              http_method: "PUT",
              full_uri: "/crud/save-guard-found-arm",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_c50e5c1cb2f688c8",
              http_method: "POST",
              full_uri: "/crud/save-guard-not-found-arm",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_45a3331794528c0c",
              http_method: "PUT",
              full_uri: "/crud/save-parameter-callers-agree",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_ed59a86b3d124f5a",
              http_method: "PUT",
              full_uri: "/crud/save-parameter-callers-disagree",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_a05ffc24ea999055",
              http_method: "POST",
              full_uri: "/crud/save-parameter-from-request-body",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_9f8264d71f2d4632",
              http_method: "PUT",
              full_uri: "/crud/save-upsert-by-branch",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_0e96032ecb4f2f4a",
              http_method: "PUT",
              full_uri: "/crud/save-via-helper-wrapper",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_359255df0a62efef",
              http_method: "PUT",
              full_uri: "/crud/two-calls-one-statement",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_5809ae39bb8afa80",
              http_method: "GET",
              full_uri: "/crud/query-jpql-join-association",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_9da93f1d3b4d7d85",
              http_method: "GET",
              full_uri: "/crud/query-jpql-keyword-entity",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_5364b7f912de2af0",
              http_method: "PUT",
              full_uri: "/crud/query-jpql-update-modifying",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_71f47a3023322fcd",
              http_method: "GET",
              full_uri: "/crud/query-named",
              call_sites: 2,
            },
            {
              endpoint_id: "ep_30230ef02c0a75be",
              http_method: "GET",
              full_uri: "/crud/query-native-table",
              call_sites: 2,
            },
            {
              endpoint_id: "ep_2332a7904fdeeaae",
              http_method: "POST",
              full_uri: "/crud/repository-custom-fragment",
              call_sites: 1,
            },
            {
              endpoint_id: "ep_da009ac1ea8d383b",
              http_method: "PUT",
              full_uri: "/crud/repository-default-method",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.OrderLine",
      name: "OrderLine",
      data_model_id: "dm_bc214a0c901d03ae",
      storage_name: null,
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_9927fb7b3b116975",
              http_method: "GET",
              full_uri: "/crud/query-jpql-select",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Pet",
      name: "Pet",
      data_model_id: "dm_6afaaf0c533fb828",
      storage_name: "pets",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [
            {
              endpoint_id: "ep_139e3e16700567c5",
              http_method: "POST",
              full_uri: "/crud/inherited-method-table",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "unknown",
          endpoints: [
            {
              endpoint_id: "ep_5a3ff882f3f2ce93",
              http_method: "GET",
              full_uri: "/crud/query-mongo-json",
              call_sites: 1,
            },
          ],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Shipment",
      name: "Shipment",
      data_model_id: "dm_56438559da4b6bc3",
      storage_name: "shipments",
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: "com.acme.crud.domain.Ticket",
      name: "Ticket",
      data_model_id: "dm_48c48e4fba697260",
      storage_name: null,
      declared_by: "annotation",
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_517fe466fa8c55ef",
              http_method: "POST",
              full_uri: "/crud/base-interface-repository",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
    {
      service_id: "svc_667da3bb12c1d42d",
      entity: null,
      name: "entity not determined",
      data_model_id: null,
      storage_name: null,
      declared_by: null,
      operations: [
        {
          operation: "create",
          endpoints: [],
        },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_dd55eb2a30c46d36",
              http_method: "GET",
              full_uri: "/crud/unbindable-entity-chain",
              call_sites: 1,
            },
          ],
        },
        {
          operation: "update",
          endpoints: [],
        },
        {
          operation: "delete",
          endpoints: [],
        },
        {
          operation: "create-or-update",
          endpoints: [],
        },
        {
          operation: "unknown",
          endpoints: [],
        },
      ],
    },
  ],
  services: [
    {
      service_id: "svc_667da3bb12c1d42d",
      service_name: "spring-data-crud-matrix",
      status: "reporting",
      accounting: {
        call_sites: 68,
        in_endpoint_flow: 67,
        in_no_endpoint_flow: 1,
        flush: 1,
        implemented_in_project: 2,
        entity_undetermined: 1,
        unknown_operation: 13,
        create_or_update: 18,
        bound: 33,
        accesses_by_operation: {
          create: 0,
          read: 28,
          update: 0,
          delete: 6,
          "create-or-update": 18,
          unknown: 15,
        },
        sites_by_basis: {
          "method-name": 36,
          "query-text": 13,
          "argument-origin": 16,
          "existence-guard": 2,
        },
        rules_version: "e4841668e407e7f7",
        gate_flags: [
          {
            basis: "argument-origin",
            operation: "create",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "argument-origin",
            operation: "update",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "existence-guard",
            operation: "create",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "existence-guard",
            operation: "update",
            enabled: false,
            scored_rules_version: null,
          },
        ],
      },
    },
  ],
}

export const CRUD_MATRIX_ENTITY_COVERAGE: EntityCoverageSection = {
  services_reporting: 1,
  services_predating: 0,
  call_sites: 68,
  in_endpoint_flow: 67,
  in_no_endpoint_flow: 1,
  flush: 1,
  implemented_in_project: 2,
  entity_undetermined: 1,
  unknown_operation: 13,
  create_or_update: 18,
  bound: 33,
  accesses_by_operation: {
    create: 0,
    read: 28,
    update: 0,
    delete: 6,
    "create-or-update": 18,
    unknown: 15,
  },
  sites_by_basis: {
    "method-name": 36,
    "query-text": 13,
    "argument-origin": 16,
    "existence-guard": 2,
  },
  by_service: [
    {
      service_id: "svc_667da3bb12c1d42d",
      service_name: "spring-data-crud-matrix",
      accounting: {
        call_sites: 68,
        in_endpoint_flow: 67,
        in_no_endpoint_flow: 1,
        flush: 1,
        implemented_in_project: 2,
        entity_undetermined: 1,
        unknown_operation: 13,
        create_or_update: 18,
        bound: 33,
        accesses_by_operation: {
          create: 0,
          read: 28,
          update: 0,
          delete: 6,
          "create-or-update": 18,
          unknown: 15,
        },
        sites_by_basis: {
          "method-name": 36,
          "query-text": 13,
          "argument-origin": 16,
          "existence-guard": 2,
        },
        rules_version: "e4841668e407e7f7",
        gate_flags: [
          {
            basis: "argument-origin",
            operation: "create",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "argument-origin",
            operation: "update",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "existence-guard",
            operation: "create",
            enabled: false,
            scored_rules_version: null,
          },
          {
            basis: "existence-guard",
            operation: "update",
            enabled: false,
            scored_rules_version: null,
          },
        ],
      },
    },
  ],
  unmeasured: [
    "cascaded-operations",
    "dirty-checking-updates",
    "other-persistence-mechanisms",
  ],
  unexercised_vocabulary: ["operation:create", "operation:update"],
  gated_operations: ["create", "update"],
}
