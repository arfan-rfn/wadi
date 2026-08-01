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
======================  ======================================================

Additions are additive (minor ``TAG_REGISTRY_VERSION`` bump); removals or
grammar changes are breaking (major bump).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from wadi_contracts.version import TAG_REGISTRY_VERSION

__all__ = [
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
    if value in ("db", "http-client"):
        return
    if _MQ_SINK_VALUE.match(value):
        return
    raise TagValidationError(
        f"sink tag value must be 'db', 'http-client', or 'mq:<broker>', got {value!r}"
    )


def _validate_model(value: str) -> None:
    if not _MODEL_VALUE.match(value):
        raise TagValidationError(f"model tag value must be an entity name, got {value!r}")


_VALIDATORS: dict[str, Callable[[str], None]] = {
    "endpoint": _validate_endpoint,
    "sink": _validate_sink,
    "model": _validate_model,
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
