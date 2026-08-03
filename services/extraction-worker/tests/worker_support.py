"""Canned ServiceExport documents for assembler/pipeline tests.

Shapes the exact spring-petstore-mini structure the Scala side will emit:
controller handler → (DI-resolved) service impl → repository sink, plus a
RestTemplate call with a recovered URL.
"""

from wadi_joern_client.export import (
    CfgNodeKind,
    ExportAnalysisCoverage,
    ExportAsyncRoot,
    ExportCall,
    ExportCfg,
    ExportCfgEdge,
    ExportCfgEdgeLabel,
    ExportCfgNode,
    ExportDataModel,
    ExportEndpoint,
    ExportMethod,
    ExportParam,
    ExportSink,
    ServiceExport,
    SinkValueConfidence,
)

CONTROLLER = 100
SERVICE_IMPL = 200
REPO_CALLSITE = 205
HTTP_CALLSITE = 207
# Inner CALL node ids (export 2.0.0 sink rows carry them for exact per-site dedup).
REPO_CALL_ID = 3205
HTTP_CALL_ID = 3207


def petstore_like_export() -> ServiceExport:
    """GET /pets/{id}: controller -> service impl (via DI) -> Mongo repo + RestTemplate."""
    methods = [
        ExportMethod(
            id=CONTROLLER,
            full_name="com.acme.pets.PetController.getPet:com.acme.pets.Pet(java.lang.String)",
            signature="getPet(String)",
            filename="src/main/java/com/acme/pets/PetController.java",
            line=14,
            line_end=17,
            code="public Pet getPet(@PathVariable String id) {",
            doc_comment="Fetches one pet by id.",
            return_type="com.acme.pets.Pet",
            params=[ExportParam(name="id", type_name="java.lang.String")],
            tags=["endpoint=GET /pets/{id}"],
        ),
        ExportMethod(
            id=SERVICE_IMPL,
            full_name="com.acme.pets.PetServiceImpl.findPet:com.acme.pets.Pet(java.lang.String)",
            signature="findPet(String)",
            filename="src/main/java/com/acme/pets/PetServiceImpl.java",
            line=20,
            line_end=31,
            code="public Pet findPet(String id) {",
            return_type="com.acme.pets.Pet",
            params=[ExportParam(name="id", type_name="java.lang.String")],
            tags=[],
        ),
    ]
    cfgs = [
        ExportCfg(
            method_id=CONTROLLER,
            nodes=[
                ExportCfgNode(
                    id=101,
                    kind=CfgNodeKind.CALL,
                    code="return petService.findPet(id);",
                    line=15,
                    line_end=15,
                    call=ExportCall(
                        callee_full_name=(
                            "com.acme.pets.PetServiceImpl.findPet:"
                            "com.acme.pets.Pet(java.lang.String)"
                        ),
                        callee_id=SERVICE_IMPL,
                        resolved=True,
                        via_di=True,
                    ),
                ),
            ],
            edges=[],
        ),
        ExportCfg(
            method_id=SERVICE_IMPL,
            nodes=[
                ExportCfgNode(
                    id=201,
                    kind=CfgNodeKind.BRANCH,
                    code="if (id == null || id.isBlank()) {",
                    line=21,
                    line_end=21,
                    condition_code="id == null || id.isBlank()",
                ),
                ExportCfgNode(
                    id=202,
                    kind=CfgNodeKind.RETURN,
                    code="throw new IllegalArgumentException();",
                    line=22,
                    line_end=22,
                ),
                ExportCfgNode(
                    id=REPO_CALLSITE,
                    kind=CfgNodeKind.CALL,
                    code="Pet pet = petRepository.findById(id).orElseThrow();",
                    line=24,
                    line_end=24,
                    call=ExportCall(
                        callee_full_name=(
                            "org.springframework.data.repository.CrudRepository.findById"
                        ),
                        resolved=False,
                    ),
                ),
                ExportCfgNode(
                    id=HTTP_CALLSITE,
                    kind=CfgNodeKind.CALL,
                    code=(
                        'inventory = restTemplate.getForObject(invUrl + "/stock/" + id, '
                        "Stock.class);"
                    ),
                    line=27,
                    line_end=27,
                    call=ExportCall(
                        callee_full_name=(
                            "org.springframework.web.client.RestTemplate.getForObject"
                        ),
                        resolved=False,
                    ),
                ),
                ExportCfgNode(
                    id=209,
                    kind=CfgNodeKind.RETURN,
                    code="return pet;",
                    line=30,
                    line_end=30,
                ),
            ],
            edges=[
                ExportCfgEdge(source=201, target=202, label=ExportCfgEdgeLabel.TRUE),
                ExportCfgEdge(source=201, target=REPO_CALLSITE, label=ExportCfgEdgeLabel.FALSE),
                ExportCfgEdge(source=REPO_CALLSITE, target=HTTP_CALLSITE),
                ExportCfgEdge(source=HTTP_CALLSITE, target=209),
            ],
        ),
    ]
    endpoints = [
        ExportEndpoint(method_id=CONTROLLER, http_method="GET", uri="/pets/{id}"),
    ]
    sinks = [
        ExportSink(
            node_id=REPO_CALLSITE,
            call_id=REPO_CALL_ID,
            method_id=SERVICE_IMPL,
            kind="db",
        ),
        # Honest Phase-1 recovery: the field-held host is lost, only the
        # concatenation template survives (matches the real Scala output —
        # the URL slicer upgrades this in M3).
        ExportSink(
            node_id=HTTP_CALLSITE,
            call_id=HTTP_CALL_ID,
            method_id=SERVICE_IMPL,
            kind="http-client",
            value="{?}/stock/{?}",
            value_confidence=SinkValueConfidence.HEURISTIC,
            http_verb="GET",
            mechanism="resttemplate",
        ),
    ]
    data_models = [
        ExportDataModel(
            entity="Pet",
            fields=[
                ExportParam(name="id", type_name="java.lang.String"),
                ExportParam(name="name", type_name="java.lang.String"),
            ],
            persistence_framework="spring-data-mongodb",
            storage_name="pets",
        )
    ]
    return ServiceExport(
        language="java",
        methods=methods,
        cfgs=cfgs,
        endpoints=endpoints,
        sinks=sinks,
        data_models=data_models,
        # 2 closure methods of 3 production: one unreached method exists so
        # tests can distinguish the counts from the closure size (§5.4.3).
        analysis_coverage=ExportAnalysisCoverage(
            production_methods=3, reachable_production_methods=2
        ),
        # T4 (§5.4.2): one non-endpoint root so the boundary fact is exercised.
        async_roots=[ExportAsyncRoot(method_id=SERVICE_IMPL, kind="scheduled")],
    )
