"""The versioned tag registry (architecture.md §7, day-zero rule).

The tag namespace is a contract, not a pack convention. Query packs may only
emit tags that validate here; artifact writes validate against this registry;
federated bundle ingestion validates vocabulary at the door and flags unknowns
by name rather than silently absorbing them (P10).

Grammar: ``<namespace>=<value>``. Registered namespaces and value grammars:

======================  ======================================================
``endpoint``            ``<HTTP-METHOD> <path>`` — e.g. ``endpoint=GET /orders``
``sink``                ``db`` | ``http-client`` | ``mq:<broker>``
``model``               entity name — e.g. ``model=Order``
``auth``                ``<source>:<raw annotation>`` where source is
                        ``annotation`` (Spring Security) or ``jsr250`` — e.g.
                        ``auth=annotation:@PreAuthorize("hasRole('ADMIN')")``.
                        Raw text is preserved verbatim (§5.2 step 5 evidence).
``auth-rule``           ``<verb>|<pattern>|<access>`` — one SecurityFilterChain
                        DSL rule; verb is an HTTP method or ``*`` — e.g.
                        ``auth-rule=*|/admin/**|hasRole('ADMIN')``
``token-propagation``   ``authorization-header`` | ``feign-interceptor`` —
                        how auth crosses an outbound call site (§5.1)
``async-root``          non-endpoint reachability root kind (§5.4.2 T4):
                        ``scheduled`` | ``event-listener`` | ``kafka-listener``
                        | ``rabbit-listener`` | ``jms-listener`` |
                        ``application-runner`` | ``bean`` |
                        ``framework-callback``
======================  ======================================================

Additions are additive (minor ``TAG_REGISTRY_VERSION`` bump); removals or
grammar changes are breaking (major bump).

**Internal tags are exempt:** tag names prefixed ``wadi-`` (e.g. ``wadi-di``,
``wadi-feign``) are exporter-private plumbing between passes and the export
step. They never appear in exported artifacts and are not part of this
registry's vocabulary.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from wadi_contracts.version import TAG_REGISTRY_VERSION

__all__ = [
    "ASYNC_ROOT_KINDS",
    "TAG_REGISTRY_VERSION",
    "Tag",
    "TagValidationError",
    "parse_tag",
    "registered_namespaces",
    "validate_tag",
]

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"})

_ENDPOINT_VALUE = re.compile(r"^(?P<method>[A-Z]+) (?P<path>/\S*)$")
_MQ_SINK_VALUE = re.compile(r"^mq:[a-z0-9][a-z0-9-]*$")
_MODEL_VALUE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")
_AUTH_VALUE = re.compile(r"^(annotation|jsr250):@.+$", re.DOTALL)
_AUTH_RULE_VALUE = re.compile(
    r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|\*)\|[^|]+\|.+$", re.DOTALL
)
_TOKEN_PROPAGATION_VALUES = frozenset({"authorization-header", "feign-interceptor"})
ASYNC_ROOT_KINDS = frozenset(
    {
        "scheduled",
        "event-listener",
        "kafka-listener",
        "rabbit-listener",
        "jms-listener",
        "application-runner",
        "bean",
        "framework-callback",
    }
)


class TagValidationError(ValueError):
    """Raised when a tag does not conform to the registered vocabulary."""


@dataclass(frozen=True, slots=True)
class Tag:
    """A parsed, validated tag."""

    namespace: str
    value: str

    def __str__(self) -> str:
        return f"{self.namespace}={self.value}"


def _validate_endpoint(value: str) -> None:
    match = _ENDPOINT_VALUE.match(value)
    if match is None:
        raise TagValidationError(
            f"endpoint tag value must be '<HTTP-METHOD> </path>', got {value!r}"
        )
    if match.group("method") not in _HTTP_METHODS:
        raise TagValidationError(f"unknown HTTP method in endpoint tag: {value!r}")


def _validate_sink(value: str) -> None:
    if value in ("db", "http-client", "http-client-suspected"):
        return
    if _MQ_SINK_VALUE.match(value):
        return
    raise TagValidationError(
        f"sink tag value must be 'db', 'http-client', 'http-client-suspected', "
        f"or 'mq:<broker>', got {value!r}"
    )


def _validate_model(value: str) -> None:
    if not _MODEL_VALUE.match(value):
        raise TagValidationError(f"model tag value must be an entity name, got {value!r}")


def _validate_auth(value: str) -> None:
    if not _AUTH_VALUE.match(value):
        raise TagValidationError(
            f"auth tag value must be '<annotation|jsr250>:@<raw annotation>', got {value!r}"
        )


def _validate_auth_rule(value: str) -> None:
    if not _AUTH_RULE_VALUE.match(value):
        raise TagValidationError(
            f"auth-rule tag value must be '<verb>|<pattern>|<access>', got {value!r}"
        )


def _validate_token_propagation(value: str) -> None:
    if value not in _TOKEN_PROPAGATION_VALUES:
        allowed = " | ".join(sorted(_TOKEN_PROPAGATION_VALUES))
        raise TagValidationError(f"token-propagation tag value must be {allowed}, got {value!r}")


def _validate_async_root(value: str) -> None:
    if value not in ASYNC_ROOT_KINDS:
        allowed = " | ".join(sorted(ASYNC_ROOT_KINDS))
        raise TagValidationError(f"async-root tag value must be {allowed}, got {value!r}")


_VALIDATORS: dict[str, Callable[[str], None]] = {
    "endpoint": _validate_endpoint,
    "sink": _validate_sink,
    "model": _validate_model,
    "auth": _validate_auth,
    "auth-rule": _validate_auth_rule,
    "token-propagation": _validate_token_propagation,
    "async-root": _validate_async_root,
}


def registered_namespaces() -> frozenset[str]:
    """The namespaces this registry version knows."""
    return frozenset(_VALIDATORS)


def parse_tag(raw: str) -> Tag:
    """Parse and validate ``namespace=value``; raises :class:`TagValidationError`."""
    namespace, separator, value = raw.partition("=")
    if not separator or not namespace or not value:
        raise TagValidationError(f"tag must have the form 'namespace=value', got {raw!r}")
    return validate_tag(namespace, value)


def validate_tag(namespace: str, value: str) -> Tag:
    """Validate a (namespace, value) pair against the registry."""
    validator = _VALIDATORS.get(namespace)
    if validator is None:
        known = ", ".join(sorted(_VALIDATORS))
        raise TagValidationError(
            f"unknown tag namespace {namespace!r} (registry v{TAG_REGISTRY_VERSION}; "
            f"known: {known})"
        )
    validator(value)
    return Tag(namespace=namespace, value=value)
