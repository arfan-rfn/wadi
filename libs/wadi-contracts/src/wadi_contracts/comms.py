"""Outbound-communication facts: HTTP remote calls and MQ interactions (§7).

Over-approximation is the correct answer for an architecture map (§5.2): a
call site whose target depends on a branch yields one ``RemoteCall`` fact per
candidate URL. Genuinely runtime-only targets keep ``url=None`` at confidence
``NONE`` — a first-class "target undetermined" fact, never silently dropped
(P10).
"""

from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import ArtifactEnvelope
from wadi_contracts.enums import Confidence, HttpMethod, MqDirection
from wadi_contracts.source import MethodRef, SourceAnchor


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
            "'authorization-header' | 'feign-interceptor' (§5.1 token-propagation evidence)"
        ),
    )

    @model_validator(mode="after")
    def _undetermined_targets_are_honest(self) -> Self:
        if self.url is None and self.url_confidence is not Confidence.NONE:
            raise ValueError("url=None requires url_confidence=NONE (undetermined target)")
        if self.url is not None and self.url_confidence is Confidence.NONE:
            raise ValueError("a recovered url must carry a confidence above NONE")
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
