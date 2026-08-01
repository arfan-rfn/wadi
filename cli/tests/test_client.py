"""API client unit tests with a mocked transport (no server)."""

import httpx
import pytest

from wadi_cli.client import ApiError, ApiUnreachableError, WadiApiClient
from wadi_contracts import RepoSource
from wadi_testing.builders import make_snapshot, make_system


def _client(handler: httpx.MockTransport) -> WadiApiClient:
    return WadiApiClient("http://testserver", transport=handler)


class TestRequestPlumbing:
    def test_bearer_token_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("Authorization", "")
            seen["version"] = request.headers.get("X-Wadi-Cli-Version", "")
            return httpx.Response(200, json=[])

        client = WadiApiClient(
            "http://testserver", token="tok", transport=httpx.MockTransport(handler)
        )
        client.list_systems()
        assert seen["auth"] == "Bearer tok"
        assert seen["version"]

    def test_transport_error_maps_to_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(ApiUnreachableError, match="wadi up"):
            client.list_systems()

    def test_http_error_maps_to_api_error_with_detail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "system sys_x not found"})

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(ApiError, match="system sys_x not found") as excinfo:
            client.list_systems()
        assert excinfo.value.status_code == 404

    def test_non_json_error_body_handled(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="<html>bad gateway</html>")

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(ApiError, match="bad gateway"):
            client.list_systems()


class TestTypedMethods:
    def test_create_system_roundtrip(self) -> None:
        system = make_system("shop")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/systems"
            return httpx.Response(201, json=system.model_dump(mode="json"))

        client = _client(httpx.MockTransport(handler))
        created = client.create_system(
            "shop", [RepoSource(source="https://github.com/acme/shop.git")]
        )
        assert created == system

    def test_analyze_parses_nested_snapshot(self) -> None:
        snapshot = make_snapshot(make_system())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={"snapshot": snapshot.model_dump(mode="json"), "job_ids": ["job_1"]},
            )

        client = _client(httpx.MockTransport(handler))
        assert client.analyze("sys_x") == snapshot

    def test_get_system_by_name(self) -> None:
        systems = [make_system("alpha"), make_system("beta")]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[s.model_dump(mode="json") for s in systems])

        client = _client(httpx.MockTransport(handler))
        found = client.get_system_by_name("beta")
        assert found is not None
        assert found.name == "beta"
        assert client.get_system_by_name("missing") is None
