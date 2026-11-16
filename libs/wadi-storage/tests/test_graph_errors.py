"""Unit tests: a graph store that fails surfaces as wadi-storage's own error.

Services never import the driver (P1), so they cannot catch its exceptions by
type, and MCP `endpoint_detail` has to catch exactly a graph failure to
degrade on one (pre-landing review #6). No container: the driver is a stand-in
that refuses every query the way an unreachable Neo4j does.
"""

from typing import cast

import pytest
from neo4j.exceptions import ClientError, ServiceUnavailable

from wadi_storage import GraphRepository, GraphStore, GraphStoreError


class _RefusingDriver:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute_query(self, *args: object, **kwargs: object) -> object:
        raise self._error


class _RefusingStore:
    def __init__(self, error: Exception) -> None:
        self.driver = _RefusingDriver(error)


def _graph_failing_with(error: Exception) -> GraphRepository:
    return GraphRepository(cast(GraphStore, _RefusingStore(error)))


class TestGraphStoreError:
    async def test_an_unreachable_store_raises_the_storage_error(self) -> None:
        driver_error = ServiceUnavailable("Unable to retrieve routing information")
        graph = _graph_failing_with(driver_error)
        with pytest.raises(GraphStoreError) as caught:
            await graph.remote_edges("snap_x", "svc_x")
        # The driver's error stays the cause, and its name stays in the
        # message a job failure records.
        assert caught.value.__cause__ is driver_error
        assert "ServiceUnavailable" in str(caught.value)
        assert "Unable to retrieve routing information" in str(caught.value)

    async def test_a_query_the_store_rejects_raises_it_too(self) -> None:
        graph = _graph_failing_with(ClientError("Invalid input"))
        with pytest.raises(GraphStoreError):
            await graph.all_edges("snap_x")

    async def test_an_error_that_is_not_the_stores_is_not_relabelled(self) -> None:
        """Only a graph failure is translated; a bug keeps its own type."""
        graph = _graph_failing_with(KeyError("missing"))
        with pytest.raises(KeyError):
            await graph.remote_edges("snap_x", "svc_x")
