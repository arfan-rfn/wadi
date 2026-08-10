"""Typed REST client for the orchestrator API (§15).

The CLI's only data path: everything goes over ``/api/v1`` with
`wadi-contracts` models, which makes the CLI the first consumer of the public
API — if the CLI can do it over REST, third parties can too (§14).
"""

import json
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

import httpx

from wadi_contracts import (
    CoverageReport,
    EndpointSummary,
    ExtractionJob,
    RemoteEdgesView,
    RepoSource,
    ServiceSummary,
    Snapshot,
    System,
)

# Single source: the installed package's own version (cli/pyproject.toml, which
# the release guard pins to the git tag). This tags the MCP passthrough image
# and names the embedded compose file — it must never drift from the release.
CLI_VERSION = version("wadi-sh")


class ApiUnreachableError(RuntimeError):
    """The orchestrator API could not be reached (exit code 3).

    Strictly a CONNECTION failure — nothing was listening, or the connection
    dropped before a response. A slow request is :class:`ApiTimeoutError`; the
    two used to be one class, so a request that was succeeding server-side told
    the user their stack was down.
    """


class ApiTimeoutError(RuntimeError):
    """The request outlived the client's patience, not the server's.

    The server may well be completing the work right now. Callers must not
    describe this as a failed request or invite a blind retry: `analyze`
    resolves commits synchronously (a first mirror-clone of an arbitrary repo),
    and retrying starts a SECOND snapshot while the first is still running.
    """

    def __init__(self, base_url: str, seconds: float, path: str = "") -> None:
        self.base_url = str(base_url)
        self.seconds = seconds
        self.path = path
        super().__init__(f"no response from {base_url} within {seconds:g}s")


class ApiError(RuntimeError):
    """The API answered with an error status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class WadiApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        # Kept so a timeout can say how long it waited — "no response within
        # 30s" tells a user what to change; "timed out" does not.
        self._timeout_seconds = timeout
        headers = {"X-Wadi-Cli-Version": CLI_VERSION}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=base_url, headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "WadiApiClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)  # type: ignore[arg-type]
        except httpx.TimeoutException as exc:
            # NOT unreachable: the connection was made and the server is
            # working. Conflating the two is what told a user with a healthy
            # stack to run `wadi up`.
            raise ApiTimeoutError(str(self._http.base_url), self._timeout_seconds, path) from exc
        except httpx.TransportError as exc:
            raise ApiUnreachableError(
                f"cannot reach the wadi API at {self._http.base_url} ({exc})"
            ) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, str(detail))
        return response

    # --- systems ---------------------------------------------------------------

    def create_system(self, name: str, repos: list[RepoSource]) -> System:
        response = self._request(
            "POST",
            "/api/v1/systems",
            json={"name": name, "repos": [repo.model_dump(mode="json") for repo in repos]},
        )
        return System.model_validate(response.json())

    def list_systems(self) -> list[System]:
        response = self._request("GET", "/api/v1/systems")
        return [System.model_validate(item) for item in response.json()]

    def get_system_by_name(self, name: str) -> System | None:
        return next((s for s in self.list_systems() if s.name == name), None)

    # --- analysis --------------------------------------------------------------

    def analyze(self, system_id: str) -> Snapshot:
        response = self._request("POST", f"/api/v1/systems/{system_id}/analyze")
        return Snapshot.model_validate(response.json()["snapshot"])

    def get_snapshot(self, snapshot_id: str) -> Snapshot:
        response = self._request("GET", f"/api/v1/snapshots/{snapshot_id}")
        return Snapshot.model_validate(response.json())

    def list_snapshots(self, system_id: str) -> list[Snapshot]:
        response = self._request("GET", f"/api/v1/systems/{system_id}/snapshots")
        return [Snapshot.model_validate(item) for item in response.json()]

    def list_jobs(self, snapshot_id: str) -> list[ExtractionJob]:
        response = self._request("GET", f"/api/v1/snapshots/{snapshot_id}/jobs")
        return [ExtractionJob.model_validate(item) for item in response.json()]

    def restitch(self, snapshot_id: str) -> Snapshot:
        """Re-run stitching over stored artifacts (recovery — no re-extraction)."""
        response = self._request("POST", f"/api/v1/snapshots/{snapshot_id}/restitch")
        return Snapshot.model_validate(response.json()["snapshot"])

    # --- read API ----------------------------------------------------------------

    def list_services(self, snapshot_id: str) -> list[ServiceSummary]:
        response = self._request("GET", f"/api/v1/snapshots/{snapshot_id}/services")
        return [ServiceSummary.model_validate(item) for item in response.json()]

    def list_endpoints(self, snapshot_id: str, service_id: str) -> list[EndpointSummary]:
        # List rows carry no wire shapes (§5.2.15); `wadi endpoints` prints
        # none of them. Fetch one endpoint's detail for a request/response shape.
        response = self._request(
            "GET", f"/api/v1/snapshots/{snapshot_id}/services/{service_id}/endpoints"
        )
        return [EndpointSummary.model_validate(item) for item in response.json()]

    def get_coverage(self, snapshot_id: str) -> CoverageReport:
        response = self._request("GET", f"/api/v1/snapshots/{snapshot_id}/coverage")
        return CoverageReport.model_validate(response.json())

    def iter_export(self, snapshot_id: str) -> Iterator[dict[str, Any]]:
        """Stream the snapshot's export bundle (§14): parsed NDJSON records,
        manifest last. Raises like :meth:`_request` on transport/API errors."""
        path = f"/api/v1/snapshots/{snapshot_id}/export"
        try:
            with self._http.stream("GET", path) as response:
                if response.status_code >= 400:
                    body = response.read()
                    try:
                        detail = json.loads(body).get("detail", body.decode())
                    except ValueError:
                        detail = body.decode()
                    raise ApiError(response.status_code, str(detail))
                for line in response.iter_lines():
                    if line.strip():
                        record: dict[str, Any] = json.loads(line)
                        yield record
        except httpx.TimeoutException as exc:
            # NOT unreachable: the connection was made and the server is
            # working. Conflating the two is what told a user with a healthy
            # stack to run `wadi up`.
            raise ApiTimeoutError(str(self._http.base_url), self._timeout_seconds, path) from exc
        except httpx.TransportError as exc:
            raise ApiUnreachableError(
                f"cannot reach the wadi API at {self._http.base_url} ({exc})"
            ) from exc

    def get_remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        response = self._request(
            "GET", f"/api/v1/snapshots/{snapshot_id}/services/{service_id}/remote-edges"
        )
        return RemoteEdgesView.model_validate(response.json())

    def healthz(self) -> dict[str, str]:
        response = self._request("GET", "/healthz")
        data: dict[str, str] = response.json()
        return data
