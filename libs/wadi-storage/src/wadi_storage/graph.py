"""Neo4j connection seam (Tier 2, §6).

Phase 1 ships the connection wrapper only; the stitcher populates the graph
in Phase 2. Kept here so no service ever imports the neo4j driver directly
(P1: `wadi-storage` is the only DB-driver importer).
"""

from types import TracebackType

from neo4j import AsyncDriver, AsyncGraphDatabase


class GraphStore:
    """Async Neo4j driver wrapper. Derived store — always rebuildable from Tier 1."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
            uri, auth=(user, password)
        )

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()  # pyright: ignore[reportUnknownMemberType]

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> "GraphStore":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def driver(self) -> AsyncDriver:
        """Escape hatch for the stitcher (the graph's single writer, P4)."""
        return self._driver
