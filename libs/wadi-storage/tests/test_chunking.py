"""Pure chunk-packing tests (no database)."""

import pytest

from wadi_storage.chunking import OversizedItemError, bson_size, needs_chunking, pack_items


def size_by_len(item: str) -> int:
    return len(item)


class TestPackItems:
    def test_empty(self) -> None:
        assert pack_items([], max_bytes=10, size_fn=size_by_len) == []

    def test_single_part_when_under_budget(self) -> None:
        items = ["aa", "bb", "cc"]
        assert pack_items(items, max_bytes=10, size_fn=size_by_len) == [items]

    def test_splits_at_budget_boundary(self) -> None:
        items = ["aaaa", "bbbb", "cccc"]  # 4 bytes each, budget 8 → [a,b], [c]
        assert pack_items(items, max_bytes=8, size_fn=size_by_len) == [
            ["aaaa", "bbbb"],
            ["cccc"],
        ]

    def test_order_preserved_on_concat(self) -> None:
        items = [f"item-{i:04d}" for i in range(100)]
        parts = pack_items(items, max_bytes=50, size_fn=size_by_len)
        flattened = [item for part in parts for item in part]
        assert flattened == items
        assert all(sum(len(i) for i in part) <= 50 for part in parts)

    def test_item_exactly_at_budget_is_its_own_part(self) -> None:
        parts = pack_items(["aaaa", "bbbbbbbbbb", "cc"], max_bytes=10, size_fn=size_by_len)
        assert parts == [["aaaa"], ["bbbbbbbbbb"], ["cc"]]

    def test_single_oversized_item_raises(self) -> None:
        with pytest.raises(OversizedItemError, match="item 1"):
            pack_items(["ok", "way-too-big-item"], max_bytes=10, size_fn=size_by_len)


class TestBsonSizing:
    def test_bson_size_measures_wrapped_value(self) -> None:
        small = bson_size({"a": 1})
        big = bson_size({"a": "x" * 10_000})
        assert big > small
        assert big > 10_000

    def test_needs_chunking_threshold(self) -> None:
        assert needs_chunking({"payload": "x" * 100}, max_bytes=50)
        assert not needs_chunking({"payload": "x"}, max_bytes=1000)
