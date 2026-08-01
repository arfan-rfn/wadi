"""Typed REST client for the orchestrator API (§15).

The CLI's only data path: everything goes over ``/api/v1`` with
`wadi-contracts` models, which makes the CLI the first consumer of the public
API — if the CLI can do it over REST, third parties can too (§14).
"""

import httpx

from wadi_contracts import (
    Endpoint,
    ExtractionJob,
    RepoSource,
    ServiceSummary,
    Snapshot,
    System,
)

CLI_VERSION = "0.1.0"


class ApiUnreachableError(RuntimeError):
    """The orchestrator API could not be reached (exit code 3)."""


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
        except httpx.TransportError as exc:
            raise ApiUnreachableError(
                f"cannot reach the wadi API at {self._http.base_url} ({exc}); "
                "is the stack up? (wadi up)"
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

    # --- read API ----------------------------------------------------------------

    def list_services(self, snapshot_id: str) -> list[ServiceSummary]:
        response = self._request("GET", f"/api/v1/snapshots/{snapshot_id}/services")
        return [ServiceSummary.model_validate(item) for item in response.json()]

    def list_endpoints(self, snapshot_id: str, service_id: str) -> list[Endpoint]:
        response = self._request(
            "GET", f"/api/v1/snapshots/{snapshot_id}/services/{service_id}/endpoints"
        )
        return [Endpoint.model_validate(item) for item in response.json()]

    def healthz(self) -> dict[str, str]:
        response = self._request("GET", "/healthz")
        data: dict[str, str] = response.json()
        return data
