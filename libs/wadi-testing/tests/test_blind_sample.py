"""The blind hand check: a seeded draw a reader can label from source alone, and
its scoring (§5.2.17, reviews D3, D4, D5).

The draw talks to the orchestrator, so these tests serve it from an in-memory
transport built from real contract models: the routes and shapes are the ones
`wadi_orchestrator.app` serves, and nothing here starts a server.
"""

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wadi_contracts import (
    EndpointDetailView,
    EndpointEntityAccess,
    EndpointSummary,
    EntityOperation,
    HttpMethod,
    Icfg,
    IcfgEdge,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    MethodRef,
    ServiceBoundary,
    ServiceKind,
    ServiceSummary,
    SourceAnchor,
    method_id,
    service_id,
)
from wadi_contracts.endpoint import Endpoint
from wadi_testing.measure.blind_sample import (
    LabelError,
    PairVerdict,
    Stratum,
    clopper_pearson_upper,
    draw,
    main,
    score,
)

SNAPSHOT = "snap_0123456789abcdef"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
C, R, U, D, COU, UNK = (
    EntityOperation.CREATE,
    EntityOperation.READ,
    EntityOperation.UPDATE,
    EntityOperation.DELETE,
    EntityOperation.CREATE_OR_UPDATE,
    EntityOperation.UNKNOWN,
)


def _row(entity: str | None, *operations: EntityOperation, sites: int = 1) -> EndpointEntityAccess:
    return EndpointEntityAccess(
        entity=entity,
        data_model_id=None,
        operations=list(operations),
        call_sites=sites,
        call_sites_by_operation={op.value: sites for op in operations},
    )


class FakeSnapshot:
    """One snapshot's services, endpoints, details and ICFGs, served as the API does."""

    def __init__(self, corpus: Path) -> None:
        self.corpus = corpus
        self.services: list[ServiceSummary] = []
        self.endpoints: dict[str, list[Endpoint]] = {}
        self.icfgs: dict[str, Icfg] = {}

    def service(
        self, name: str, *, kind: ServiceKind = ServiceKind.SERVICE, build_root: str | None = None
    ) -> ServiceSummary:
        root = build_root or name
        boundary = ServiceBoundary(
            snapshot_id=SNAPSHOT,
            service_id=service_id(str(self.corpus), root),
            name=name,
            repo=str(self.corpus),
            build_root=root,
            languages=["java"],
            build_system="maven",
            kind=kind,
        )
        summary = ServiceSummary(**boundary.model_dump(), endpoint_count=0)
        self.services.append(summary)
        self.endpoints[summary.service_id] = []
        return summary

    def endpoint(
        self,
        service: ServiceSummary,
        uri: str,
        entity_access: list[EndpointEntityAccess] | None,
        *,
        handler: str = "com.acme.web.OrderController.show",
        file: str = "src/main/java/com/acme/web/OrderController.java",
        line: int = 20,
        method: HttpMethod = HttpMethod.GET,
        icfg: bool = True,
    ) -> Endpoint:
        signature = f"{handler}:java.lang.Object(java.lang.String)"
        ref = MethodRef(id=method_id(service.service_id, signature), signature=signature)
        endpoint = Endpoint.create(
            snapshot_id=SNAPSHOT,
            service_id=service.service_id,
            http_method=method,
            full_uri=uri,
            handler=ref,
            entity_access=entity_access,
        )
        self.endpoints[service.service_id].append(endpoint)
        if not icfg:
            return endpoint
        entry = IcfgNode(
            id="entry",
            kind=IcfgNodeKind.ENTRY,
            anchor=SourceAnchor(file=file, start_line=line, end_line=line),
            source_text="public Object show(String id) {",
            method=ref,
        )
        exit_node = entry.model_copy(update={"id": "exit", "kind": IcfgNodeKind.EXIT})
        self.icfgs[endpoint.id] = Icfg(
            snapshot_id=SNAPSHOT,
            service_id=service.service_id,
            endpoint_id=endpoint.id,
            entry_node_id="entry",
            nodes=[entry, exit_node],
            edges=[IcfgEdge(source="entry", target="exit", kind=IcfgEdgeKind.FLOW)],
        )
        return endpoint

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url="http://orchestrator.test/api/v1", transport=httpx.MockTransport(self.serve)
        )

    def serve(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.removeprefix("/api/v1/").split("/")
        body: Any
        match parts:
            case ["snapshots", snap, "services"] if snap == SNAPSHOT:
                body = [s.model_dump(mode="json") for s in self.services]
            case ["snapshots", snap, "services", svc, "endpoints"] if snap == SNAPSHOT:
                body = [
                    EndpointSummary.model_validate(
                        e.model_dump(exclude={"request_schema", "response_schema", "type_defs"})
                    ).model_dump(mode="json")
                    for e in self.endpoints[svc]
                ]
            case ["snapshots", snap, "endpoints", ep, "detail"] if snap == SNAPSHOT:
                endpoint = self._find(ep)
                service = next(s for s in self.services if s.service_id == endpoint.service_id)
                body = EndpointDetailView(
                    snapshot_id=SNAPSHOT,
                    system_id="sys_0123456789abcdef",
                    service_id=service.service_id,
                    service_name=service.name,
                    endpoint=endpoint,
                    icfg_available=ep in self.icfgs,
                    stitched=True,
                ).model_dump(mode="json")
            case ["snapshots", snap, "endpoints", ep, "icfg"] if snap == SNAPSHOT:
                if ep not in self.icfgs:
                    return httpx.Response(404, json={"detail": "no ICFG"})
                body = self.icfgs[ep].model_dump(mode="json")
            case _:
                return httpx.Response(404, json={"detail": f"no route {request.url.path}"})
        return httpx.Response(200, json=body)

    def _find(self, endpoint_id: str) -> Endpoint:
        return next(e for es in self.endpoints.values() for e in es if e.id == endpoint_id)


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("class X {}\n")


@pytest.fixture
def snapshot(tmp_path: Path) -> FakeSnapshot:
    """Twelve endpoints over two services, three of them hard.

    Hard: two entities (`/orders/multi`), three call sites on one entity
    (`/orders/busy`), and an undetermined row beside a named one
    (`/billing/mixed`).
    """
    corpus = tmp_path / "corpus"
    fake = FakeSnapshot(corpus)
    orders = fake.service("orders")
    billing = fake.service("billing")
    fake.service("common", kind=ServiceKind.LIBRARY)
    _write(corpus, "orders/src/main/java/com/acme/web/OrderController.java")
    _write(corpus, "billing/src/main/java/com/acme/web/OrderController.java")
    for index in range(6):
        fake.endpoint(orders, f"/orders/{index}", [_row("com.acme.Order", R)])
    fake.endpoint(orders, "/orders/none", [])
    fake.endpoint(orders, "/orders/old", None)
    fake.endpoint(orders, "/orders/multi", [_row("com.acme.Order", R), _row("com.acme.Line", D)])
    fake.endpoint(orders, "/orders/busy", [_row("com.acme.Order", R, COU, sites=3)])
    fake.endpoint(billing, "/billing/one", [_row("com.acme.Invoice", R)])
    fake.endpoint(billing, "/billing/mixed", [_row("com.acme.Invoice", R), _row(None, R)])
    return fake


def _draw(fake: FakeSnapshot, *, seed: int = 7, size: int = 4) -> tuple[Any, Any]:
    with fake.client() as client:
        result = draw(client, SNAPSHOT, seed=seed, size=size, corpus=fake.corpus, now=NOW)
    return result.blind, result.key


HARD = {"/orders/multi", "/orders/busy", "/billing/mixed"}


class TestTheDraw:
    def test_a_seed_gives_the_same_draw_and_another_seed_another(
        self, snapshot: FakeSnapshot
    ) -> None:
        first, second, other = _draw(snapshot), _draw(snapshot), _draw(snapshot, seed=8)

        assert first == second
        assert [e["full_uri"] for e in first[0]["endpoints"]] != [
            e["full_uri"] for e in other[0]["endpoints"]
        ]

    def test_the_random_stratum_is_a_simple_random_sample_of_every_endpoint(
        self, snapshot: FakeSnapshot
    ) -> None:
        # Drawn from every endpoint, sorted by id so the draw does not depend
        # on the order the API lists them; predating and empty endpoints too.
        population = sorted(e.id for es in snapshot.endpoints.values() for e in es)

        _, key = _draw(snapshot, seed=7, size=4)

        drawn = [e["endpoint_id"] for e in key["endpoints"] if e["stratum"] == "random"]
        assert sorted(drawn) == sorted(random.Random(7).sample(population, 4))
        assert (key["seed"], key["size"], key["population"]) == (7, 4, 12)
        assert (key["snapshot_id"], key["drawn_at"]) == (SNAPSHOT, NOW.isoformat())

    def test_every_hard_endpoint_is_drawn_once_and_reported_apart(
        self, snapshot: FakeSnapshot
    ) -> None:
        _, key = _draw(snapshot, seed=7, size=4)

        by_uri = {e["full_uri"]: e["stratum"] for e in key["endpoints"]}
        assert len(by_uri) == len(key["endpoints"])
        assert set(by_uri) >= HARD
        # A hard endpoint the random draw already took stays in the random
        # stratum, so that stratum is still a simple random sample.
        random_uris = {uri for uri, stratum in by_uri.items() if stratum == "random"}
        assert {uri for uri, stratum in by_uri.items() if stratum == "hard"} == HARD - random_uris
        assert key["hard_population"] == 3

    def test_the_key_carries_wadis_answer_for_each_endpoint(self, snapshot: FakeSnapshot) -> None:
        _, key = _draw(snapshot, seed=7, size=12)

        by_uri = {e["full_uri"]: e["entity_access"] for e in key["endpoints"]}
        assert by_uri["/orders/old"] is None
        assert by_uri["/orders/none"] == []
        assert [row["entity"] for row in by_uri["/billing/mixed"]] == ["com.acme.Invoice", None]

    def test_nothing_wadi_concluded_reaches_the_blind_file(self, snapshot: FakeSnapshot) -> None:
        blind, key = _draw(snapshot, seed=7, size=12)

        assert {field for e in blind["endpoints"] for field in e} == {
            "id",
            "service",
            "http_method",
            "full_uri",
            "handler_class",
            "handler_method",
            "source_file",
            "line",
        }
        # Beside the rows, only the format version and how to write labels.
        assert set(blind) == {"blind_format", "labels", "endpoints"}
        text = json.dumps(blind["endpoints"])
        for leaked in ("Invoice", "Line", "entity_access", "operation", "call_site", "stratum"):
            assert leaked not in text
        # The order says nothing either: sorted by service and route, so the
        # hard endpoints are not the last few rows.
        rows = [(e["service"], e["full_uri"], e["http_method"]) for e in blind["endpoints"]]
        assert rows == sorted(rows)
        assert [e["id"] for e in blind["endpoints"]] == [f"b{n:03d}" for n in range(1, 13)]
        assert {e["id"] for e in key["endpoints"]} == {e["id"] for e in blind["endpoints"]}

    def test_a_reader_is_pointed_at_the_handler_from_the_corpus_root(
        self, snapshot: FakeSnapshot
    ) -> None:
        blind, _ = _draw(snapshot, seed=7, size=12)

        row = next(e for e in blind["endpoints"] if e["full_uri"] == "/billing/one")
        assert row == {
            "id": row["id"],
            "service": "billing",
            "http_method": "GET",
            "full_uri": "/billing/one",
            "handler_class": "com.acme.web.OrderController",
            "handler_method": "show",
            "source_file": "billing/src/main/java/com/acme/web/OrderController.java",
            "line": 20,
        }

    def test_staged_library_source_resolves_to_the_library_and_a_missing_file_to_none(
        self, tmp_path: Path
    ) -> None:
        # §5.2.14 stages a library's sources under `wadi-libs/<root>/` in the
        # dependent's parse; the reader needs the file where it really lives.
        corpus = tmp_path / "corpus"
        fake = FakeSnapshot(corpus)
        app = fake.service("app")
        fake.service("shared", kind=ServiceKind.LIBRARY, build_root="libs/shared")
        _write(corpus, "libs/shared/src/main/java/com/acme/lib/LibController.java")
        fake.endpoint(
            app,
            "/lib",
            [],
            file="wadi-libs/shared/src/main/java/com/acme/lib/LibController.java",
        )
        fake.endpoint(app, "/gone", [], file="src/main/java/com/acme/Gone.java")
        fake.endpoint(app, "/no-graph", [], icfg=False)

        with fake.client() as client:
            blind = draw(client, SNAPSHOT, seed=1, size=3, corpus=corpus, now=NOW).blind

        assert {e["full_uri"]: (e["source_file"], e["line"]) for e in blind["endpoints"]} == {
            "/lib": ("libs/shared/src/main/java/com/acme/lib/LibController.java", 20),
            "/gone": (None, 20),
            "/no-graph": (None, None),
        }

    def test_a_sample_larger_than_the_snapshot_is_refused(self, snapshot: FakeSnapshot) -> None:
        with snapshot.client() as client, pytest.raises(ValueError, match="12 endpoints"):
            draw(client, SNAPSHOT, seed=1, size=13, corpus=snapshot.corpus, now=NOW)

    def test_the_command_writes_both_files(
        self, snapshot: FakeSnapshot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "check"
        transport = httpx.MockTransport(snapshot.serve)

        code = main(
            [
                *("draw", "--snapshot", SNAPSHOT, "--seed", "7", "--size", "4"),
                *("--corpus", str(snapshot.corpus), "--out-dir", str(out)),
                *("--api", "http://orchestrator.test/api/v1"),
            ],
            transport=transport,
        )

        assert code == 0
        blind = json.loads((out / "blind.json").read_text())
        key = json.loads((out / "key.json").read_text())
        assert len(blind["endpoints"]) == len(key["endpoints"]) >= 4
        assert "random 4" in capsys.readouterr().out


def _key(*endpoints: tuple[str, Stratum, list[EndpointEntityAccess] | None]) -> dict[str, Any]:
    """A key.json holding (sample id, stratum, wadi's rows) per endpoint."""
    return {
        "key_format": "1",
        "snapshot_id": SNAPSHOT,
        "seed": 7,
        "size": sum(stratum is Stratum.RANDOM for _, stratum, _ in endpoints),
        "drawn_at": NOW.isoformat(),
        "api": "http://orchestrator.test/api/v1",
        "population": 100,
        "hard_population": sum(stratum is Stratum.HARD for _, stratum, _ in endpoints),
        "endpoints": [
            {
                "id": sample_id,
                "endpoint_id": f"ep_{index:016x}",
                "stratum": stratum.value,
                "service": "orders",
                "http_method": "GET",
                "full_uri": f"/{sample_id}",
                "entity_access": (
                    None if rows is None else [row.model_dump(mode="json") for row in rows]
                ),
            }
            for index, (sample_id, stratum, rows) in enumerate(endpoints)
        ],
    }


def _truth(*accesses: tuple[str, str]) -> list[dict[str, Any]]:
    """Reader labels: (entity, comma-separated operations)."""
    return [{"entity": entity, "operations": ops.split(",")} for entity, ops in accesses]


def _one(
    rows: list[EndpointEntityAccess], truth: list[dict[str, Any]]
) -> list[tuple[str | None, PairVerdict]]:
    report = score(_key(("b001", Stratum.RANDOM, rows)), {"b001": truth})
    [endpoint] = report.endpoints
    return [(pair.entity, pair.verdict) for pair in endpoint.pairs]


class TestScoringRules:
    def test_the_same_entity_and_verbs_is_exact(self) -> None:
        assert _one([_row("com.acme.Order", R, D)], _truth(("Order", "read,delete"))) == [
            ("Order", PairVerdict.EXACT)
        ]

    def test_create_or_update_for_a_create_or_an_update_is_less_specific(self) -> None:
        # Consistent with the truth and weaker than it: the save split was
        # withheld by its gate, and that is not an error.
        assert _one([_row("com.acme.Order", COU)], _truth(("Order", "create"))) == [
            ("Order", PairVerdict.LESS_SPECIFIC)
        ]
        assert _one([_row("com.acme.Order", COU)], _truth(("Order", "create,update"))) == [
            ("Order", PairVerdict.LESS_SPECIFIC)
        ]
        assert _one([_row("com.acme.Order", R, COU)], _truth(("Order", "read,update"))) == [
            ("Order", PairVerdict.LESS_SPECIFIC)
        ]

    def test_unknown_or_an_undetermined_entity_over_a_true_access_is_withheld(self) -> None:
        assert _one([_row("com.acme.Order", UNK)], _truth(("Order", "update"))) == [
            ("Order", PairVerdict.WITHHELD)
        ]
        # Review D3's #10: a native query on `station` whose entity wadi could
        # not name, read by the reader as Station read.
        assert _one([_row(None, R)], _truth(("Station", "read"))) == [
            ("Station", PairVerdict.WITHHELD)
        ]

    def test_a_verb_the_truth_does_not_have_is_an_over_claim(self) -> None:
        assert _one([_row("com.acme.Order", R, D)], _truth(("Order", "read"))) == [
            ("Order", PairVerdict.OVER_CLAIM)
        ]
        # create-or-update claims a write; a read-only truth has none.
        assert _one([_row("com.acme.Order", COU)], _truth(("Order", "read"))) == [
            ("Order", PairVerdict.OVER_CLAIM)
        ]

    def test_an_entity_the_truth_does_not_touch_is_an_over_claim(self) -> None:
        assert _one(
            [_row("com.acme.Order", R), _row("com.acme.Invoice", UNK)], _truth(("Order", "read"))
        ) == [("Order", PairVerdict.EXACT), ("com.acme.Invoice", PairVerdict.OVER_CLAIM)]

    def test_a_true_access_wadi_does_not_cover_is_a_miss(self) -> None:
        assert _one([_row("com.acme.Order", R)], _truth(("Order", "read,delete"))) == [
            ("Order", PairVerdict.MISS)
        ]
        assert _one([_row("com.acme.Order", R)], _truth(("Order", "read"), ("Line", "delete"))) == [
            ("Order", PairVerdict.EXACT),
            ("Line", PairVerdict.MISS),
        ]
        # An undetermined row covers only the verbs it names.
        assert _one([_row(None, D)], _truth(("Station", "read"))) == [
            ("Station", PairVerdict.MISS),
            (None, PairVerdict.OVER_CLAIM),
        ]

    def test_an_undetermined_row_restating_a_named_access_is_withheld(self) -> None:
        assert _one([_row("com.acme.Order", R), _row(None, R)], _truth(("Order", "read"))) == [
            ("Order", PairVerdict.EXACT),
            (None, PairVerdict.WITHHELD),
        ]

    def test_labels_of_one_entity_merge_and_qualified_labels_tell_namesakes_apart(
        self,
    ) -> None:
        crm, billing = _row("com.acme.crm.Account", R), _row("com.acme.billing.Account", D)

        assert _one([crm, billing], _truth(("com.acme.crm.Account", "read"))) == [
            ("com.acme.crm.Account", PairVerdict.EXACT),
            ("com.acme.billing.Account", PairVerdict.OVER_CLAIM),
        ]
        assert _one(
            [_row("com.acme.Order", R, D)], _truth(("Order", "read"), ("Order", "delete"))
        ) == [("Order", PairVerdict.EXACT)]
        with pytest.raises(LabelError, match="ambiguous"):
            _one([crm, billing], _truth(("Account", "read")))

    def test_a_label_outside_the_four_verbs_is_refused(self) -> None:
        with pytest.raises(LabelError):
            _one([_row("com.acme.Order", R)], _truth(("Order", "create-or-update")))


class TestScoreReport:
    def test_endpoint_agreement_and_errors_are_counted_per_stratum(self) -> None:
        rows = [_row("com.acme.Order", R)]
        exact = [(f"r{n:02d}", Stratum.RANDOM, rows) for n in range(19)]
        key = _key(
            *exact,
            ("r19", Stratum.RANDOM, [_row("com.acme.Order", R, D)]),
            ("h01", Stratum.HARD, [_row("com.acme.Order", COU), _row("com.acme.Line", R)]),
            ("h02", Stratum.HARD, []),
        )
        labels: dict[str, Any] = {sample_id: _truth(("Order", "read")) for sample_id, _, _ in exact}
        labels |= {
            "r19": _truth(("Order", "read")),
            "h01": _truth(("Order", "create"), ("Line", "read")),
            "h02": [],
        }

        report = score(key, labels)

        random_stratum, hard = report.strata[Stratum.RANDOM], report.strata[Stratum.HARD]
        assert (random_stratum.endpoints, random_stratum.full_agreement) == (20, 19)
        assert random_stratum.errors == 1
        assert random_stratum.pairs[PairVerdict.EXACT] == 19
        assert random_stratum.pairs[PairVerdict.OVER_CLAIM] == 1
        assert random_stratum.error_rate_upper_95 == pytest.approx(0.2161, abs=1e-4)
        # Less specific is consistent, so h01 is no error, and an endpoint
        # with no access on either side agrees fully.
        assert (hard.endpoints, hard.full_agreement, hard.errors) == (2, 1, 0)
        assert hard.pairs[PairVerdict.LESS_SPECIFIC] == 1
        assert hard.error_rate_upper_95 == pytest.approx(1 - 0.05**0.5)

    def test_predating_unlabeled_and_unknown_labels_are_reported_not_scored(self) -> None:
        key = _key(
            ("b001", Stratum.RANDOM, [_row("com.acme.Order", R)]),
            ("b002", Stratum.RANDOM, None),
            ("b003", Stratum.RANDOM, [_row("com.acme.Order", R)]),
            ("b004", Stratum.RANDOM, [_row("com.acme.Order", R)]),
        )
        # A label may be keyed by the endpoint id instead of the sample id.
        labels = {
            "b001": _truth(("Order", "read")),
            "ep_0000000000000003": _truth(("Order", "read")),
            "b999": [],
        }

        report = score(key, labels)

        assert report.strata[Stratum.RANDOM].endpoints == 2
        assert report.predating == ["b002"]
        assert report.unlabeled == ["b003"]
        assert report.unknown_labels == ["b999"]

    def test_the_command_writes_the_report_and_fails_while_any_endpoint_is_unlabeled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        key_path, labels_path, out = (tmp_path / n for n in ("key.json", "labels.json", "s.json"))
        key_path.write_text(json.dumps(_key(("b001", Stratum.RANDOM, [_row("com.acme.Order", R)]))))
        labels_path.write_text(json.dumps({"b001": _truth(("Order", "read"))}))
        argv = ["score", "--key", str(key_path), "--labels", str(labels_path), "--json", str(out)]

        assert main(argv) == 0
        written = json.loads(out.read_text())
        assert written["strata"]["random"]["full_agreement"] == 1
        assert written["endpoints"][0]["pairs"][0]["verdict"] == "exact"
        assert (
            "random: 1 endpoints, 1 in full agreement, 0 with an error" in capsys.readouterr().out
        )

        labels_path.write_text("{}")
        assert main(argv) == 1


class TestClopperPearson:
    @pytest.mark.parametrize(
        ("errors", "n", "upper"),
        [
            # 1 - 0.05 ** (1 / n) when no error is seen: review D4's 14% and 53%.
            (0, 20, 0.139108),
            (0, 4, 0.527129),
            (1, 20, 0.216106),
            (2, 30, 0.195326),
            (5, 5, 1.0),
        ],
    )
    def test_one_sided_95_percent_upper_bound(self, errors: int, n: int, upper: float) -> None:
        assert clopper_pearson_upper(errors, n) == pytest.approx(upper, abs=1e-6)

    def test_no_endpoints_has_no_bound(self) -> None:
        assert clopper_pearson_upper(0, 0) is None
