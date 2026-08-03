"""CLI tests for `wadi export`: layout, determinism guards, failure modes."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from support import plain
from typer.testing import CliRunner

from wadi_cli import main as cli_main
from wadi_cli.client import WadiApiClient
from wadi_cli.main import app
from wadi_contracts import ExportManifest
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_icfg,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

runner = CliRunner()


@pytest.fixture
def mock_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[httpx.MockTransport], None]:
    def install(transport: httpx.MockTransport) -> None:
        def factory() -> WadiApiClient:
            return WadiApiClient("http://testserver", transport=transport)

        monkeypatch.setattr(cli_main, "_api_client", factory)

    return install


def _stream_body(include_manifest: bool = True, corrupt_counts: bool = False) -> tuple[str, str]:
    """A realistic export stream built from contract models; returns (body, snapshot_id)."""
    system = make_system()
    snapshot = make_snapshot(system)
    caller = make_service(snapshot, "services/orders")
    callee = make_service(snapshot, "services/billing")
    endpoint = make_endpoint(snapshot, callee, uri="/invoices/{id}")
    call = make_remote_call(snapshot, caller, line=12)
    records: list[tuple[str, str]] = [
        ("system", system.model_dump_json()),
        ("snapshot", snapshot.model_dump_json()),
        ("service_boundary", caller.model_dump_json()),
        ("service_boundary", callee.model_dump_json()),
        ("endpoint", endpoint.model_dump_json()),
        ("icfg", make_icfg(snapshot, callee, endpoint).model_dump_json()),
        ("remote_call", call.model_dump_json()),
        ("stitched_edge", make_analyzed_edge(call, endpoint).model_dump_json()),
    ]
    counts: dict[str, int] = {}
    for kind, _ in records:
        counts[kind] = counts.get(kind, 0) + 1
    if corrupt_counts:
        counts["endpoint"] = 99
    if include_manifest:
        manifest = ExportManifest(
            wadi_version="0.0.0-test",
            system_id=system.id,
            snapshot_id=snapshot.id,
            artifact_counts=dict(sorted(counts.items())),
        )
        records.append(("manifest", manifest.model_dump_json()))
    body = "".join(
        '{"kind":"' + kind + '","artifact":' + artifact + "}\n" for kind, artifact in records
    )
    return body, snapshot.id


def _transport_for(body: str, snapshot_id: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/snapshots/{snapshot_id}/export")
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "application/x-ndjson"}
        )

    return httpx.MockTransport(handler)


class TestExportCommand:
    def test_writes_the_layout(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        body, snapshot_id = _stream_body()
        mock_api(_transport_for(body, snapshot_id))
        target = tmp_path / "out"

        result = runner.invoke(app, ["export", snapshot_id, "--dir", str(target)])
        assert result.exit_code == 0, result.output

        manifest: dict[str, Any] = json.loads((target / "manifest.json").read_text())
        assert manifest["snapshot_id"] == snapshot_id
        assert json.loads((target / "system.json").read_text())["name"] == "shop"
        boundaries = json.loads((target / "service_boundaries.json").read_text())
        assert [b["name"] for b in boundaries] == ["orders", "billing"]
        endpoints = json.loads((target / "endpoints.json").read_text())
        assert len(endpoints) == 1
        icfg_file = target / "icfgs" / f"{endpoints[0]['id']}.json"
        assert icfg_file.exists()
        # Deterministic layout: empty collections still get their (empty) files.
        assert json.loads((target / "mq_interactions.json").read_text()) == []
        assert json.loads((target / "data_models.json").read_text()) == []
        assert "exported 8 artifacts" in plain(result.output)

    def test_json_output(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        body, snapshot_id = _stream_body()
        mock_api(_transport_for(body, snapshot_id))
        result = runner.invoke(
            app, ["export", snapshot_id, "--dir", str(tmp_path / "out"), "--json"]
        )
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["artifact_counts"]["service_boundary"] == 2

    def test_truncated_stream_writes_nothing(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        """No manifest trailer = truncated (§14): fail, leave no partial bundle."""
        body, snapshot_id = _stream_body(include_manifest=False)
        mock_api(_transport_for(body, snapshot_id))
        target = tmp_path / "out"
        result = runner.invoke(app, ["export", snapshot_id, "--dir", str(target)])
        assert result.exit_code == 1
        assert "truncated" in plain(result.output)
        assert not target.exists()

    def test_count_mismatch_fails(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        body, snapshot_id = _stream_body(corrupt_counts=True)
        mock_api(_transport_for(body, snapshot_id))
        target = tmp_path / "out"
        result = runner.invoke(app, ["export", snapshot_id, "--dir", str(target)])
        assert result.exit_code == 1
        assert "incomplete export" in plain(result.output)
        assert not target.exists()

    def test_refuses_non_empty_dir_without_force(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        body, snapshot_id = _stream_body()
        mock_api(_transport_for(body, snapshot_id))
        target = tmp_path / "out"
        target.mkdir()
        (target / "stale.json").write_text("{}")

        refused = runner.invoke(app, ["export", snapshot_id, "--dir", str(target)])
        assert refused.exit_code == 2
        assert "--force" in plain(refused.output)

        forced = runner.invoke(app, ["export", snapshot_id, "--dir", str(target), "--force"])
        assert forced.exit_code == 0, forced.output
        assert (target / "manifest.json").exists()

    def test_api_error_maps_to_exit_1(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "only succeeded snapshots export"})

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["export", "snap_x", "--dir", str(tmp_path / "out")])
        assert result.exit_code == 1
        assert "only succeeded" in plain(result.output)

    def test_unreachable_maps_to_exit_3(
        self, mock_api: Callable[[httpx.MockTransport], None], tmp_path: Path
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["export", "snap_x", "--dir", str(tmp_path / "out")])
        assert result.exit_code == 3
