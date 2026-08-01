"""Transparent chunking for oversized ICFG documents (§6).

A fat endpoint's ICFG can exceed Mongo's 16MB document limit — and the
unhandled failure mode is a write error at the *end* of an expensive
extraction. Oversized graphs are split into a manifest document plus part
documents; readers see one logical artifact through the repository API.

The packing logic is pure (size function injected) so it is unit-testable
without a database.
"""

from collections.abc import Callable, Sequence

import bson

MONGO_MAX_DOC_BYTES = 16 * 1024 * 1024
# Headroom for the envelope fields, field names, and BSON overhead around the payload.
SAFE_PART_BYTES = 12 * 1024 * 1024


class OversizedItemError(ValueError):
    """A single item exceeds the per-document budget — cannot be stored at all."""


def bson_size(document: object) -> int:
    """Encoded BSON size of a document (wrapped, so any value is measurable)."""
    return len(bson.encode({"v": document}))


def pack_items[ItemT](
    items: Sequence[ItemT],
    *,
    max_bytes: int = SAFE_PART_BYTES,
    size_fn: Callable[[ItemT], int] = bson_size,
) -> list[list[ItemT]]:
    """Greedily pack ``items`` into consecutive groups each under ``max_bytes``.

    Order is preserved (parts concatenate back to the original sequence).
    Raises :class:`OversizedItemError` if any single item exceeds the budget.
    """
    parts: list[list[ItemT]] = []
    current: list[ItemT] = []
    current_size = 0
    for index, item in enumerate(items):
        item_size = size_fn(item)
        if item_size > max_bytes:
            raise OversizedItemError(
                f"item {index} is {item_size} bytes, exceeding the {max_bytes}-byte "
                "per-document budget"
            )
        if current and current_size + item_size > max_bytes:
            parts.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size
    if current:
        parts.append(current)
    return parts


def needs_chunking(document: dict[str, object], *, max_bytes: int = SAFE_PART_BYTES) -> bool:
    return len(bson.encode(document)) > max_bytes
