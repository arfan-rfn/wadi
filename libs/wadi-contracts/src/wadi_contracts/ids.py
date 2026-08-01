"""Deterministic, content-derived identifiers (architecture.md §7, day-zero rule).

The same logical entity keeps the same id across snapshots, so cross-snapshot
history and diffing is a join, not a matching problem. IDs are derived from
stable content only — never random per run.

Every id kind is domain-separated inside the hash input *and* carries a typed
prefix in its output form, so ids of different kinds can never collide or be
confused in logs and storage keys.
"""

import hashlib
import re
from urllib.parse import urlsplit

_HASH_LENGTH = 16  # 64 bits — collision probability negligible at realistic entity counts

_PATH_PARAM_PLACEHOLDER = "{?}"

# `{id}`, `{orderId:[0-9]+}` (Spring regex form) — an entire path segment that is a template.
_TEMPLATE_SEGMENT = re.compile(r"^\{[^/{}]*(?::[^{}]*)?\}$")
# Express-style `:id` segments (future languages; normalized identically).
_COLON_SEGMENT = re.compile(r"^:[A-Za-z_][A-Za-z0-9_]*$")


def _digest(kind: str, *parts: str) -> str:
    payload = "\x1f".join((kind, *parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


def simplify_uri(uri: str) -> str:
    """Normalize a route URI to its identity form with ``{?}`` placeholders.

    Rules: path-only (scheme/host/query/fragment stripped), leading slash,
    duplicate slashes collapsed, trailing slash stripped (except root), and
    every templated path segment (``{id}``, ``{orderId:[0-9]+}``, ``:id``)
    replaced by ``{?}``. Literal segment case is preserved — HTTP paths are
    case-sensitive.
    """
    stripped = uri.strip()
    if "://" in stripped:
        stripped = urlsplit(stripped).path
    else:
        # Drop query/fragment from bare paths. A '?' inside a '{?}' placeholder
        # is part of the identity form, not a query start — skip it so the
        # function stays idempotent.
        stripped = re.split(r"(?<!\{)\?", stripped, maxsplit=1)[0]
        stripped = stripped.split("#", 1)[0]

    segments = [s for s in stripped.split("/") if s]
    normalized: list[str] = []
    for segment in segments:
        if _TEMPLATE_SEGMENT.match(segment) or _COLON_SEGMENT.match(segment):
            normalized.append(_PATH_PARAM_PLACEHOLDER)
        else:
            normalized.append(segment)
    return "/" + "/".join(normalized)


def normalize_repo_source(source: str) -> str:
    """Canonical form of a repo source (URL or local path) for identity purposes.

    URLs: scheme dropped, host lowercased, ``.git`` suffix and trailing slash
    stripped, scp-like ``git@host:org/repo`` recognized — so the same repo
    reached via https/ssh/scp syntax yields one identity. Local paths are
    kept verbatim apart from trailing-slash stripping (they are only
    meaningful within one deployment).
    """
    src = source.strip()
    scp_match = re.match(r"^(?:[A-Za-z0-9_.-]+@)([A-Za-z0-9_.-]+):(?!//)(.+)$", src)
    if scp_match:
        host, path = scp_match.group(1).lower(), scp_match.group(2)
        return _canonical_repo(host, path)
    if "://" in src:
        parts = urlsplit(src)
        host = (parts.hostname or "").lower()
        return _canonical_repo(host, parts.path)
    return src.rstrip("/") or "/"


def _canonical_repo(host: str, path: str) -> str:
    clean = path.strip("/")
    clean = clean.removesuffix(".git")
    return f"{host}/{clean}"


def service_id(repo_source: str, build_root: str) -> str:
    """Stable id for a service: derived from its repo and build root.

    Survives renames of the *service name* (display metadata); changes only if
    the service moves to a different build root or repo — which genuinely is a
    different service location.
    """
    normalized_root = build_root.strip().strip("/") or "."
    return "svc_" + _digest("service", normalize_repo_source(repo_source), normalized_root)


def endpoint_id(svc_id: str, http_method: str, uri: str) -> str:
    """Stable id for an endpoint: hash of service + method + simplified URI (§7)."""
    return "ep_" + _digest("endpoint", svc_id, http_method.strip().upper(), simplify_uri(uri))


def method_id(svc_id: str, full_signature: str) -> str:
    """Stable id for a method within a service, keyed by fully-qualified signature."""
    return "m_" + _digest("method", svc_id, full_signature.strip())


def remote_call_id(svc_id: str, file: str, line: int, candidate_url: str) -> str:
    """Stable id for one remote-call fact (one per candidate URL, §5.2)."""
    return "rc_" + _digest("remote-call", svc_id, file, str(line), candidate_url)


def mq_interaction_id(svc_id: str, file: str, line: int, direction: str, topic: str) -> str:
    """Stable id for one message-queue interaction fact."""
    return "mq_" + _digest("mq", svc_id, file, str(line), direction, topic)


def data_model_id(svc_id: str, entity_name: str) -> str:
    """Stable id for a persisted data model within a service."""
    return "dm_" + _digest("data-model", svc_id, entity_name.strip())
