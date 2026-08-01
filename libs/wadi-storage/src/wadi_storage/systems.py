"""System + Snapshot repositories. Single writer: the orchestrator (P4)."""

from wadi_contracts import Snapshot, SnapshotStatus, System
from wadi_contracts.timeutil import utc_now
from wadi_storage.codec import from_doc, to_doc
from wadi_storage.mongo import SNAPSHOTS, SYSTEMS, WadiDatabase


class DuplicateSystemNameError(ValueError):
    """A system with this name is already registered."""


class SystemRepository:
    def __init__(self, database: WadiDatabase) -> None:
        self._col = database.collection(SYSTEMS)

    async def insert(self, system: System) -> None:
        from pymongo.errors import DuplicateKeyError

        try:
            await self._col.insert_one(to_doc(system))
        except DuplicateKeyError as exc:
            raise DuplicateSystemNameError(
                f"a system named {system.name!r} (or with id {system.id!r}) already exists"
            ) from exc

    async def get(self, system_id: str) -> System | None:
        doc = await self._col.find_one({"id": system_id})
        return from_doc(System, doc) if doc else None

    async def get_by_name(self, name: str) -> System | None:
        doc = await self._col.find_one({"name": name})
        return from_doc(System, doc) if doc else None

    async def list_all(self) -> list[System]:
        cursor = self._col.find().sort([("created_at", 1), ("_id", 1)])
        return [from_doc(System, doc) async for doc in cursor]


class SnapshotRepository:
    def __init__(self, database: WadiDatabase) -> None:
        self._col = database.collection(SNAPSHOTS)

    async def insert(self, snapshot: Snapshot) -> None:
        await self._col.insert_one(to_doc(snapshot))

    async def get(self, snapshot_id: str) -> Snapshot | None:
        doc = await self._col.find_one({"id": snapshot_id})
        return from_doc(Snapshot, doc) if doc else None

    async def list_for_system(self, system_id: str) -> list[Snapshot]:
        # _id breaks same-millisecond created_at ties (insertion order).
        cursor = self._col.find({"system_id": system_id}).sort([("created_at", -1), ("_id", -1)])
        return [from_doc(Snapshot, doc) async for doc in cursor]

    async def set_status(
        self, snapshot_id: str, status: SnapshotStatus, *, error: str | None = None
    ) -> None:
        """Update run status. Snapshot *content* (commits) is immutable (§4)."""
        update: dict[str, object] = {"status": status.value}
        if status is SnapshotStatus.RUNNING:
            update["started_at"] = utc_now()
        elif status in (SnapshotStatus.SUCCEEDED, SnapshotStatus.FAILED):
            update["finished_at"] = utc_now()
        if error is not None:
            update["error"] = error
        await self._col.update_one({"id": snapshot_id}, {"$set": update})
