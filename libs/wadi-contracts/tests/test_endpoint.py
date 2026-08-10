"""Endpoint model tests: identity enforcement and honest auth."""

import pytest
from pydantic import ValidationError

from wadi_contracts.endpoint import (
    AuthEffect,
    AuthEvidence,
    AuthEvidenceKind,
    AuthMechanism,
    AuthMechanismKind,
    AuthRelationship,
    AuthResolution,
    Endpoint,
    EndpointAuth,
    EndpointParam,
    FieldShape,
    ParamLocation,
    ShapeKind,
    TypeShape,
    resolve_type_shape,
)
from wadi_contracts.enums import HttpMethod, TriggerKind
from wadi_contracts.ids import endpoint_id
from wadi_contracts.source import MethodRef


class TestEndpointCreate:
    def test_derives_id_and_simplified_uri(self, svc_id: str, handler_ref: MethodRef) -> None:
        ep = Endpoint.create(
            snapshot_id="snap_" + "0" * 16,
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{orderId}",
            handler=handler_ref,
        )
        assert ep.simplified_uri == "/orders/{?}"
        assert ep.id == endpoint_id(svc_id, "GET", "/orders/{orderId}")
        assert ep.trigger is TriggerKind.HTTP

    def test_root_anchors_a_slashless_route(self, svc_id: str, handler_ref: MethodRef) -> None:
        """Spring routes `api/v1/x` exactly as `/api/v1/x` (§5.2.11)."""
        ep = Endpoint.create(
            snapshot_id="snap_" + "0" * 16,
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="api/v1/configservice/configs",
            handler=handler_ref,
        )
        assert ep.full_uri == "/api/v1/configservice/configs"
        # The two spellings were always ONE endpoint: the id hashes
        # simplify_uri, which has always anchored the root. Normalizing the
        # published fact therefore costs no identity churn.
        assert ep.id == endpoint_id(svc_id, "GET", "/api/v1/configservice/configs")

    def test_slashless_route_loads_from_an_older_snapshot(
        self, svc_id: str, handler_ref: MethodRef
    ) -> None:
        """Coerced, not rejected — stored snapshots predate the rule."""
        stored = Endpoint.create(
            snapshot_id="snap_" + "0" * 16,
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/api/v1/configservice/configs",
            handler=handler_ref,
        ).model_dump()
        stored["full_uri"] = "api/v1/configservice/configs"  # as written pre-1.19.0
        reloaded = Endpoint.model_validate(stored)
        assert reloaded.full_uri == "/api/v1/configservice/configs"
        assert reloaded.id == stored["id"]

    @pytest.mark.parametrize("uri", ["{?}/pets/list", "${gateway.base}/pets"])
    def test_leaves_an_unknown_head_alone(
        self, uri: str, svc_id: str, handler_ref: MethodRef
    ) -> None:
        """A hole or a config template has an unknown head.

        Asserting a leading slash in front of one would invent information the
        analysis does not have (P10) — the expansion may well supply its own.
        """
        ep = Endpoint.create(
            snapshot_id="snap_" + "0" * 16,
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri=uri,
            handler=handler_ref,
        )
        assert ep.full_uri == uri

    def test_same_logical_endpoint_same_id(self, svc_id: str, handler_ref: MethodRef) -> None:
        a = Endpoint.create(
            snapshot_id="snap_a",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{orderId}",
            handler=handler_ref,
        )
        b = Endpoint.create(
            snapshot_id="snap_b",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{id}",  # param renamed between snapshots
            handler=handler_ref,
        )
        assert a.id == b.id


class TestEndpointIdentityEnforcement:
    def test_rejects_wrong_id(self, svc_id: str, handler_ref: MethodRef) -> None:
        with pytest.raises(ValidationError, match="content-derived"):
            Endpoint(
                snapshot_id="snap",
                service_id=svc_id,
                id="ep_" + "0" * 16,
                http_method=HttpMethod.GET,
                full_uri="/orders",
                simplified_uri="/orders",
                handler=handler_ref,
            )

    def test_rejects_wrong_simplified_uri(self, svc_id: str, handler_ref: MethodRef) -> None:
        with pytest.raises(ValidationError, match="simplified_uri"):
            Endpoint(
                snapshot_id="snap",
                service_id=svc_id,
                id=endpoint_id(svc_id, "GET", "/orders/{id}"),
                http_method=HttpMethod.GET,
                full_uri="/orders/{id}",
                simplified_uri="/orders/{id}",  # not the {?} form
                handler=handler_ref,
            )


class TestEndpointAuth:
    def test_default_is_unknown(self) -> None:
        auth = EndpointAuth()
        assert auth.authenticated is None
        assert auth.roles == []

    def test_claim_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            EndpointAuth(authenticated=True)

    def test_claim_with_evidence(self) -> None:
        auth = EndpointAuth(
            authenticated=True,
            roles=["ADMIN"],
            mechanism="spring-security",
            evidence=[
                AuthEvidence(
                    kind=AuthEvidenceKind.ANNOTATION,
                    detail="@PreAuthorize(\"hasRole('ADMIN')\")",
                )
            ],
        )
        assert auth.roles == ["ADMIN"]

    def test_negative_claim_also_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            EndpointAuth(authenticated=False)


def _opaque(detail: str = "{?} -> permitAll()") -> AuthEvidence:
    """A guard that was detected but could not be read (§5.2.9)."""
    return AuthEvidence(
        kind=AuthEvidenceKind.SECURITY_DSL,
        detail=detail,
        effect=AuthEffect.PERMIT_ALL,
        resolution=AuthResolution.OPAQUE,
        pattern="{?}",
    )


def _resolved(role: str = "ADMIN") -> AuthEvidence:
    return AuthEvidence(
        kind=AuthEvidenceKind.SECURITY_DSL,
        detail=f'/x/** -> hasRole("{role}")',
        effect=AuthEffect.REQUIRE_ROLES,
        resolution=AuthResolution.RESOLVED,
        roles=[role],
        pattern="/x/**",
    )


class TestClaimWithholding:
    """The §5.2.9 rule, enforced by the contract rather than by convention.

    The defect this exists to prevent, measured on train-ticket: a rule whose
    pattern could not be read was dropped, so the endpoint fell through to a
    later ``permitAll()`` and published ``authenticated=False`` for a route
    that actually required ROLE_ADMIN/ROLE_USER.
    """

    def test_unread_guard_forbids_an_evidenced_open_claim(self) -> None:
        # The dangerous direction: "nothing guards this" is exactly what an
        # unread guard makes unsayable.
        with pytest.raises(ValidationError, match="detected but not read"):
            EndpointAuth(authenticated=False, evidence=[_opaque()])

    def test_unread_guard_does_not_forbid_a_protected_claim(self) -> None:
        # Enforcement is a conjunction, so an unread gate can only ADD a
        # requirement. Withholding here would throw away a sound answer: a
        # resolved rule already demands ADMIN, and nothing unread can undo it.
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved(), _opaque()])
        assert auth.authenticated is True

    def test_an_unread_bypass_forbids_even_a_protected_claim(self) -> None:
        # Bypasses are the one construct that REMOVES enforcement, so an
        # unreadable one could flip protected to open.
        bypass = AuthEvidence(
            kind=AuthEvidenceKind.CHAIN_BYPASS,
            detail="{?} bypasses the security chain",
            effect=AuthEffect.PERMIT_ALL,
            resolution=AuthResolution.OPAQUE,
            pattern="{?}",
        )
        with pytest.raises(ValidationError, match="detected but not read"):
            EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved(), bypass])

    def test_withheld_claim_keeps_the_reason_queryable(self) -> None:
        auth = EndpointAuth(authenticated=None, evidence=[_resolved(), _opaque()])
        assert [item.kind for item in auth.unread_enforcement] == [AuthEvidenceKind.SECURITY_DSL]

    def test_an_inactive_guard_does_not_gate_and_does_not_withhold(self) -> None:
        # @Secured under @EnableMethodSecurity(securedEnabled=false) is inert:
        # recorded so the reader sees it, but it enforces nothing.
        inert = AuthEvidence(
            kind=AuthEvidenceKind.ANNOTATION,
            detail='@Secured("ROLE_ADMIN")',
            resolution=AuthResolution.OPAQUE,
            active=False,
            inactive_reason="securedEnabled=false",
        )
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[inert, _resolved()])
        assert auth.unread_enforcement == []

    def test_fully_read_guards_permit_a_claim(self) -> None:
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved()])
        assert auth.authenticated is True

    def test_partial_resolution_does_not_withhold(self) -> None:
        # hasAnyRole(ADMIN_CONST, "USER") — one role recovered, one not. The
        # claim (auth IS required) is sound; only the role list is incomplete.
        partial = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail='/x/** -> hasAnyRole(admin, "USER")',
            effect=AuthEffect.REQUIRE_ROLES,
            resolution=AuthResolution.PARTIAL,
            roles=["USER"],
            expression='hasAnyRole(admin, "USER")',
        )
        assert EndpointAuth(authenticated=True, roles=["USER"], evidence=[partial]).authenticated


class TestActiveFlagged:
    def test_inactive_requires_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="inactive_reason"):
            AuthEvidence(kind=AuthEvidenceKind.ANNOTATION, detail="@Secured", active=False)

    def test_a_relationship_effect_without_its_relationship_is_rejected(self) -> None:
        # §5.2.12. The effect and the payload cannot disagree about what an
        # enforcement requires: `require-relationship` with nothing attached is
        # a claim with its content missing, and a reader would render an empty
        # requirement as no requirement.
        with pytest.raises(ValidationError, match="requires a relationship"):
            AuthEvidence(
                kind=AuthEvidenceKind.ASPECT,
                detail="ContestManagerAuthorizer via @ContestManager",
                effect=AuthEffect.REQUIRE_RELATIONSHIP,
            )

    def test_a_relationship_filed_under_another_effect_is_rejected(self) -> None:
        # The mirror image: content no consumer will look for. The claim rule
        # reads relationships off `requiring` by effect, so one attached to
        # REQUIRE_ROLES would be silently dropped rather than published.
        with pytest.raises(ValidationError, match="only meaningful"):
            AuthEvidence(
                kind=AuthEvidenceKind.ASPECT,
                detail="@ContestManager",
                effect=AuthEffect.REQUIRE_ROLES,
                relationship=AuthRelationship(relation="contest-manager"),
            )

    def test_a_relationship_carries_its_own_authorities(self) -> None:
        # `@ContestManager(context = Contest.class, acl = CONTEST_UPDATE)`
        # demands BOTH. They live on the relationship so the conjunction
        # survives — pooled into a flat list they read as a menu.
        evidence = AuthEvidence(
            kind=AuthEvidenceKind.ASPECT,
            detail="ContestManagerAuthorizer via @ContestManager",
            effect=AuthEffect.REQUIRE_RELATIONSHIP,
            relationship=AuthRelationship(
                relation="contest-manager",
                resource_type="Contest",
                authorities=["CONTEST_UPDATE"],
            ),
        )
        assert evidence.relationship is not None
        assert evidence.relationship.authorities == ["CONTEST_UPDATE"]
        # Best-effort and never invented: the advice body names the parameter,
        # and reading it is Tier-2 work.
        assert evidence.relationship.resource_binding is None

    def test_covers_route_defaults_true_and_is_not_a_reading_failure(self) -> None:
        # §5.2.13. Scope and readability are different facts: a rule read
        # perfectly can still govern part of a route.
        partial = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail="/contest/public/** -> permitAll()",
            effect=AuthEffect.PERMIT_ALL,
            covers_route=False,
        )
        assert partial.resolution is AuthResolution.RESOLVED
        assert partial.covers_route is False
        assert (
            AuthEvidence(kind=AuthEvidenceKind.ANNOTATION, detail="@Secured").covers_route is True
        )

    def test_reason_without_inactive_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="inactive_reason"):
            AuthMechanism(
                kind=AuthMechanismKind.HTTP_BASIC, detail="httpBasic()", inactive_reason="huh"
            )

    def test_disabled_mechanism_is_recorded_not_dropped(self) -> None:
        # train-ticket does httpBasic().disable() on 39 services — reporting it
        # as an active mechanism would be a fabricated fact.
        mechanism = AuthMechanism(
            kind=AuthMechanismKind.HTTP_BASIC,
            detail="httpBasic()",
            active=False,
            inactive_reason="disabled in chain",
        )
        assert mechanism.active is False


class TestBackwardCompatibility:
    def test_pre_enforcement_artifact_parses_and_keeps_its_claim(self) -> None:
        # Stored artifacts predate effect/resolution; defaults must preserve
        # what they were written with rather than invalidate them.
        auth = EndpointAuth.model_validate(
            {
                "authenticated": True,
                "roles": ["ADMIN"],
                "mechanism": "spring-security",
                "evidence": [{"kind": "security-dsl", "detail": '/a/** -> hasRole("ADMIN")'}],
            }
        )
        assert auth.authenticated is True
        assert auth.evidence[0].effect is AuthEffect.UNKNOWN
        assert auth.evidence[0].resolution is AuthResolution.RESOLVED
        assert auth.mechanisms == []


class TestEndpointParams:
    def test_params(self, svc_id: str, handler_ref: MethodRef) -> None:
        ep = Endpoint.create(
            snapshot_id="snap",
            service_id=svc_id,
            http_method=HttpMethod.POST,
            full_uri="/orders",
            handler=handler_ref,
            params=[
                EndpointParam(name="body", location=ParamLocation.BODY, type_name="OrderRequest"),
                EndpointParam(
                    name="dryRun", location=ParamLocation.QUERY, type_name="boolean", required=False
                ),
            ],
        )
        assert {p.location for p in ep.params} == {ParamLocation.BODY, ParamLocation.QUERY}


class TestResolveTypeShape:
    """Reading a shape means resolving its refs (§5.2.16).

    Shapes travel as a graph — each type defined once, referenced wherever it
    occurs — because inline expansion of an entity model is exponentially
    redundant: one real response wrote 2,365 object definitions of which 113
    were distinct. A consumer that does not resolve is reading an incomplete
    shape while believing it is complete, which is why this lives in the
    contract rather than in each reader.
    """

    @staticmethod
    def _obj(type_name: str, fields: dict[str, TypeShape]) -> TypeShape:
        # Fields passed as a dict, not kwargs: a field really can be called
        # `name`, and this helper must not shadow it.
        return TypeShape(
            kind=ShapeKind.OBJECT,
            type_name=type_name,
            fields=[FieldShape(name=k, shape=v) for k, v in fields.items()],
        )

    def test_a_ref_is_replaced_by_its_definition(self) -> None:
        defs = {
            "Site": self._obj(
                "Site", {"city": TypeShape(kind=ShapeKind.SCALAR, type_name="String")}
            )
        }
        shape = self._obj("Contest", {"site": TypeShape(kind=ShapeKind.REF, type_name="Site")})
        resolved = resolve_type_shape(shape, defs)
        site = resolved.fields[0].shape
        assert site.kind is ShapeKind.OBJECT
        assert [f.name for f in site.fields] == ["city"]

    def test_the_same_type_resolves_everywhere_it_appears(self) -> None:
        """The point of sharing: one definition, many uses, all complete."""
        defs = {
            "Site": self._obj(
                "Site", {"city": TypeShape(kind=ShapeKind.SCALAR, type_name="String")}
            )
        }
        shape = self._obj(
            "Contest",
            {
                "a": TypeShape(kind=ShapeKind.REF, type_name="Site"),
                "b": TypeShape(kind=ShapeKind.REF, type_name="Site"),
            },
        )
        resolved = resolve_type_shape(shape, defs)
        assert all(f.shape.kind is ShapeKind.OBJECT for f in resolved.fields)

    def test_recursion_stops_and_stays_a_ref(self) -> None:
        """A genuine cycle cannot be inlined, and must not loop forever.

        The ref is left in place rather than replaced by a terminal: unlike the
        old `cycle` node, the reader can follow `type_defs` and see what is in
        the loop.
        """
        defs = {
            "Node": self._obj("Node", {"next": TypeShape(kind=ShapeKind.REF, type_name="Node")})
        }
        resolved = resolve_type_shape(TypeShape(kind=ShapeKind.REF, type_name="Node"), defs)
        assert resolved.kind is ShapeKind.OBJECT
        assert resolved.fields[0].shape.kind is ShapeKind.REF

    def test_a_ref_with_no_definition_is_left_alone(self) -> None:
        """Never fabricate: an unresolvable ref stays visible as one (P10)."""
        shape = TypeShape(kind=ShapeKind.REF, type_name="Missing")
        assert resolve_type_shape(shape, {}) == shape

    def test_shapes_without_refs_pass_through_unchanged(self) -> None:
        """Snapshots written before 1.25.0 are fully inline."""
        shape = self._obj("Pet", {"name": TypeShape(kind=ShapeKind.SCALAR, type_name="String")})
        assert resolve_type_shape(shape, {}) == shape

    def test_refs_inside_collections_resolve(self) -> None:
        defs = {
            "Tag": self._obj("Tag", {"v": TypeShape(kind=ShapeKind.SCALAR, type_name="String")})
        }
        shape = TypeShape(
            kind=ShapeKind.ARRAY,
            type_name="List",
            element=TypeShape(kind=ShapeKind.REF, type_name="Tag"),
        )
        resolved = resolve_type_shape(shape, defs)
        assert resolved.element is not None
        assert resolved.element.kind is ShapeKind.OBJECT
