"""Outbound-communication facts: HTTP remote calls and MQ interactions (§7).

Over-approximation is the correct answer for an architecture map (§5.2): a
call site whose target depends on a branch yields one ``RemoteCall`` fact per
candidate URL. Genuinely runtime-only targets keep ``url=None`` at confidence
``NONE`` — a first-class "target undetermined" fact, never silently dropped
(P10).
"""

from enum import StrEnum
from typing import Self, cast

from pydantic import Field, model_validator

from wadi_contracts.base import ArtifactEnvelope
from wadi_contracts.enums import Confidence, HttpMethod, MqDirection
from wadi_contracts.source import MethodRef, SourceAnchor


class Reachability(StrEnum):
    """WHICH root reaches this call site (§5.2.11 T2).

    ``reachable`` answers "is it on the map"; this answers "why". The
    distinction is load-bearing because the two false-ish cases are not the
    same fact: a call reached only from a ``CommandLineRunner`` or
    ``@Scheduled`` method genuinely runs in production — it seeds data, it hits
    other services — while a call in a vendored class no root reaches is dead.
    Publishing both as ``reachable=False`` made the first invisible and the
    second look identical to it.
    """

    ENDPOINT = "endpoint"
    """On some endpoint handler's interprocedural path — the stitchable case."""

    ASYNC_ROOT = "async-root"
    """Reached only from a non-HTTP root (startup runner, scheduled task,
    listener, framework callback). Real execution, no request behind it, so it
    is deliberately NOT stitched into endpoint flow — but it is not dead."""

    UNREACHED = "unreached"
    """No root reaches it. Dead or unwired code (P10: recorded, not dropped)."""


class TokenPropagation(StrEnum):
    """WHETHER the caller's credentials cross this call (§5.2.11 T4).

    ``auth_propagation`` names the mechanism when there is one; this says
    whether there is one at all, and — the part a nullable string could not
    express — distinguishes "we proved it does not" from "we could not tell".
    The difference decides whether a downstream 401 is a finding or a shrug.
    """

    FORWARDED = "forwarded"
    """Evidence found: inbound headers reach the outbound request, an
    ``Authorization`` header is set explicitly, or a Feign interceptor adds one."""

    NOT_FORWARDED = "not-forwarded"
    """PROVABLE absence: the request this site sends was built with no headers
    argument at all (``new HttpEntity(null)`` — 98 sites on
    train-ticket-aitest). Claimed only where it is provable, never inferred
    from silence."""

    UNDETERMINED = "undetermined"
    """A header-bearing argument exists but could not be traced. Neither
    direction is over-approximated: claiming forwarding would say credentials
    propagate when they may not, and claiming its absence would invent a
    finding (P10)."""


class RemoteCall(ArtifactEnvelope):
    """One candidate outbound HTTP call from one call site."""

    id: str = Field(pattern=r"^rc_[0-9a-f]{16}$")
    site: SourceAnchor
    method: MethodRef = Field(description="Method containing the call site")
    mechanism: str = Field(min_length=1, description="Client library, e.g. 'resttemplate'")
    http_verb: HttpMethod | None = None
    url: str | None = Field(
        default=None,
        description="Sliced candidate URL/template; None = target undetermined (P10)",
    )
    url_confidence: Confidence
    evidence: str | None = Field(
        default=None, description="Raw slice evidence behind the recovered URL"
    )
    auth_propagation: str | None = Field(
        default=None,
        description=(
            "How auth crosses this call, when statically visible: "
            "'authorization-header' | 'feign-interceptor' (§5.1 token-propagation evidence). "
            "See `auth_propagation_state` for WHETHER it crosses at all"
        ),
    )
    auth_propagation_state: TokenPropagation = Field(
        default=TokenPropagation.UNDETERMINED,
        description=(
            "Whether the caller's credentials cross this call (§5.2.11 T4). "
            "Refines `auth_propagation`: a named mechanism implies 'forwarded'"
        ),
    )
    reachable: bool = Field(
        default=True,
        description=(
            "False = no ENDPOINT-reachable path leads here. Excluded from "
            "stitching by design; inventoried so the exclusion is queryable "
            "(§5.2.5). See `reachability` for which root reaches it — False "
            "alone does not mean dead"
        ),
    )
    reachability: Reachability = Field(
        default=Reachability.ENDPOINT,
        description=(
            "Which root reaches this call: endpoint | async-root | unreached "
            "(§5.2.11 T2). Refines `reachable`, never contradicts it"
        ),
    )
    suspected: bool = Field(
        default=False,
        description=(
            "True = HTTP-shaped call on a receiver the CPG could not "
            "type-resolve — a countable maybe, never matched or blended into "
            "resolved results (P7, §5.2.5)"
        ),
    )

    @model_validator(mode="after")
    def _undetermined_targets_are_honest(self) -> Self:
        if self.url is None and self.url_confidence is not Confidence.NONE:
            raise ValueError("url=None requires url_confidence=NONE (undetermined target)")
        if self.url is not None and self.url_confidence is Confidence.NONE:
            raise ValueError("a recovered url must carry a confidence above NONE")
        return self

    @model_validator(mode="before")
    @classmethod
    def _default_reachability_from_reachable(cls, data: object) -> object:
        """Derive the refinement when only the old boolean was written.

        Snapshots stored before §5.2.11 T2 carry ``reachable`` and no
        ``reachability``; so does any caller that has not been taught the new
        field. Defaulting the enum blindly to ``endpoint`` would make every one
        of those documents fail the agreement check below — unreadable data
        bought for an invariant. ``False`` degrades to ``unreached``, which is
        what the field meant before the async-root case was split out of it.
        """
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, object], data)
        if payload.get("reachability") is not None:
            return payload
        reachable = payload.get("reachable", True)
        if isinstance(reachable, bool):
            payload["reachability"] = (
                Reachability.ENDPOINT.value if reachable else Reachability.UNREACHED.value
            )
        return payload

    @model_validator(mode="after")
    def _a_named_mechanism_means_forwarded(self) -> Self:
        """A mechanism IS the evidence of forwarding — the two cannot disagree.

        Naming ``authorization-header`` while claiming ``not-forwarded`` would
        publish both halves of a contradiction and let a reader pick.
        """
        if self.auth_propagation and self.auth_propagation_state is not TokenPropagation.FORWARDED:
            raise ValueError(
                f"auth_propagation={self.auth_propagation!r} names a mechanism, so the "
                f"state must be 'forwarded', not {self.auth_propagation_state.value!r}"
            )
        return self

    @model_validator(mode="after")
    def _reachability_refines_reachable(self) -> Self:
        """The two fields answer different questions but cannot disagree.

        ``reachability`` REFINES ``reachable``: endpoint-reachable is exactly
        the stitchable case its consumers already filter on, so a drift between
        them would silently change what gets stitched.
        """
        endpoint_rooted = self.reachability is Reachability.ENDPOINT
        if self.reachable != endpoint_rooted:
            raise ValueError(
                f"reachable={self.reachable} contradicts reachability="
                f"{self.reachability.value}: endpoint-rooted calls are exactly "
                "the reachable ones"
            )
        return self


class MqInteraction(ArtifactEnvelope):
    """One message-queue publish or consume site."""

    id: str = Field(pattern=r"^mq_[0-9a-f]{16}$")
    direction: MqDirection
    broker: str = Field(min_length=1, description="e.g. 'kafka', 'rabbitmq'")
    topic: str | None = Field(
        default=None, description="Sliced topic/queue name; None = undetermined (P10)"
    )
    topic_confidence: Confidence
    site: SourceAnchor
    method: MethodRef

    @model_validator(mode="after")
    def _undetermined_topics_are_honest(self) -> Self:
        if self.topic is None and self.topic_confidence is not Confidence.NONE:
            raise ValueError("topic=None requires topic_confidence=NONE (undetermined topic)")
        if self.topic is not None and self.topic_confidence is Confidence.NONE:
            raise ValueError("a recovered topic must carry a confidence above NONE")
        return self
