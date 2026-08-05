"""Endpoint id collisions are resolved visibly, never by silent overwrite (§7).

The 2026-08-05 incident: two controllers whose class prefixes truncated to the
same text produced three identical `(verb, uri)` pairs. Ids are content-derived
from exactly those, so the store's upsert key matched and the second write
replaced the first — three endpoints of a real controller gone, with the
coverage report reading clean because the loss happened downstream of it.

These tests pin the mechanism, not the cause. Any future defect that makes two
URIs equal lands in the same place.
"""

from wadi_contracts import Endpoint, HttpMethod, MethodRef
from wadi_worker.assembler import AssembledArtifacts, resolve_id_collisions


def _endpoint(snapshot: str, service: str, uri: str, signature: str) -> Endpoint:
    return Endpoint.create(
        snapshot_id=snapshot,
        service_id=service,
        http_method=HttpMethod.GET,
        full_uri=uri,
        handler=MethodRef(id="m_" + "0" * 16, signature=signature),
    )


def _resolve(endpoints: list[Endpoint]) -> AssembledArtifacts:
    artifacts = AssembledArtifacts(endpoints=list(endpoints))
    resolve_id_collisions(artifacts)
    return artifacts


class TestCollisionIsRecorded:
    def test_the_icpc_shape_is_caught(self) -> None:
        # Two controllers, same truncated URI — the exact incident shape.
        person = _endpoint("snap_1", "svc_1", "/search/all", "a.PersonSearchController.search:x()")
        team = _endpoint("snap_1", "svc_1", "/search/all", "b.TeamSearchController.search:x()")
        assert person.id == team.id, "precondition: content-derived ids collide"

        artifacts = _resolve([person, team])

        assert len(artifacts.endpoints) == 1, "only one row can be stored"
        assert len(artifacts.endpoint_collisions) == 1
        collision = artifacts.endpoint_collisions[0]
        assert collision.endpoint_id == person.id
        assert collision.uri == "/search/all"
        assert collision.kept_handler == "a.PersonSearchController.search:x()"
        assert collision.dropped_handlers == ["b.TeamSearchController.search:x()"]

    def test_the_winner_is_deterministic(self) -> None:
        # A reproducible snapshot needs the same survivor regardless of the
        # order the export happened to list handlers in.
        a = _endpoint("snap_1", "svc_1", "/x", "aaa.A.h:x()")
        b = _endpoint("snap_1", "svc_1", "/x", "zzz.Z.h:x()")
        forward = _resolve([a, b])
        reverse = _resolve([b, a])
        assert forward.endpoints[0].handler.signature == "aaa.A.h:x()"
        assert reverse.endpoints[0].handler.signature == "aaa.A.h:x()"
        assert forward.endpoint_collisions == reverse.endpoint_collisions

    def test_three_way_collision_names_every_loser(self) -> None:
        eps = [_endpoint("snap_1", "svc_1", "/x", f"p.C{i}.h:x()") for i in range(3)]
        artifacts = _resolve(eps)
        assert len(artifacts.endpoints) == 1
        assert artifacts.endpoint_collisions[0].dropped_handlers == [
            "p.C1.h:x()",
            "p.C2.h:x()",
        ]


class TestNoFalsePositives:
    def test_distinct_uris_do_not_collide(self) -> None:
        # What the URI fix restores: the prefixes tell the controllers apart.
        person = _endpoint("snap_1", "svc_1", "/person/search/all", "a.P.search:x()")
        team = _endpoint("snap_1", "svc_1", "/team/search/all", "b.T.search:x()")
        artifacts = _resolve([person, team])
        assert len(artifacts.endpoints) == 2
        assert artifacts.endpoint_collisions == []

    def test_a_clean_service_records_nothing(self) -> None:
        artifacts = _resolve([_endpoint("snap_1", "svc_1", "/a", "p.A.h:x()")])
        assert artifacts.endpoint_collisions == []

    def test_same_uri_in_different_services_is_not_a_collision(self) -> None:
        # Ids are scoped by service, so two services may share a URI.
        a = _endpoint("snap_1", "svc_1", "/health", "p.A.h:x()")
        b = _endpoint("snap_1", "svc_2", "/health", "p.B.h:x()")
        assert a.id != b.id
