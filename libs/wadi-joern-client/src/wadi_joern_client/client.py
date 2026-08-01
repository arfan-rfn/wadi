"""Minimal CPGQL-server client (control channel only, §5.1).

The upstream ``cpgqls-client`` package is dormant, and the protocol is two
endpoints — so wadi owns this thin client. Verified server behavior
(Joern 4.0.593):

    POST /query          {"query": "..."} -> 200 {"success": true, "uuid": "..."}
    GET  /result/<uuid>  -> 200 {"success": false, "err": "No result (yet?)..."}   (running)
                         -> 200 {"success": true, "uuid": ..., "stdout": "..."}    (finished)

REPL semantics: ``success`` means *evaluated*, not *worked* — even a compile
error arrives as success with the error text in stdout. Callers must
validate the stdout content (``run_pipeline_from_source`` checks for the
pipeline's summary marker).

The query channel carries *control* (run pipeline, small results). Bulk
graph data always travels via the shared-volume export files — never through
this channel (the query server's known weak spot).
"""

import re
import time

import httpx

_ANSI_ESCAPES = re.compile(r"\x1b\[[0-9;]*m")

PIPELINE_SUMMARY_MARKER = "wadi export:"


class JoernError(RuntimeError):
    """A Joern query failed; carries the server's stderr."""

    def __init__(self, message: str, stderr: str = "") -> None:
        self.stderr = stderr
        super().__init__(message if not stderr else f"{message}\n{stderr}")


class JoernUnreachableError(JoernError):
    """The CPGQL server is not reachable."""


class JoernClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        request_timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> None:
        auth = (username, password) if username and password else None
        self._http = httpx.Client(base_url=base_url, auth=auth, timeout=request_timeout)
        self._poll_interval = poll_interval

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "JoernClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def is_ready(self) -> bool:
        try:
            self.execute("1 + 1", timeout=30)
        except JoernError:
            return False
        return True

    def execute(self, query: str, *, timeout: float = 3600.0) -> str:
        """Run a CPGQL query to completion; returns stdout, raises on failure."""
        try:
            submitted = self._http.post("/query", json={"query": query})
        except httpx.TransportError as exc:
            raise JoernUnreachableError(f"CPGQL server unreachable: {exc}") from exc
        if submitted.status_code >= 400:
            raise JoernError(f"query submission failed ({submitted.status_code})")
        uuid = submitted.json()["uuid"]

        deadline = time.monotonic() + timeout
        while True:
            try:
                result = self._http.get(f"/result/{uuid}")
            except httpx.TransportError as exc:
                raise JoernUnreachableError(f"CPGQL server unreachable: {exc}") from exc
            if result.status_code == 200:
                body = result.json()
                if body.get("success") and "uuid" in body:
                    return _ANSI_ESCAPES.sub("", str(body.get("stdout", "")))
                # "success": false + "err" = not finished yet — keep polling.
            elif result.status_code != 404:
                raise JoernError(f"result polling failed ({result.status_code})")
            if time.monotonic() > deadline:
                raise JoernError(f"query timed out after {timeout}s")
            time.sleep(self._poll_interval)

    # --- wadi-specific control operations ---------------------------------------

    def import_code(self, source_path: str, project_name: str) -> None:
        """Import a build root via the console (frontend runs as a subprocess).

        Delombok runs in types-only mode: type information from delombok, but
        analysis on the ORIGINAL source, so anchors align with committed text
        (§5.3 source-on-demand guarantee; validated by lombok-mini).
        """
        source = _scala_string(source_path)
        project = _scala_string(project_name)
        stdout = self.execute(
            f"importCode.java(inputPath={source}, projectName={project}, "
            f'args=List("--delombok-mode", "types-only"))'
        )
        if "Cpg[" not in stdout:
            # REPL "success" only means evaluated — failures land in stdout.
            raise JoernError(f"import of {source_path} failed", stdout)

    def run_wadi_pipeline(self, export_dir: str) -> str:
        """Run the in-graph side (DI pass + packs + bulk export) from our jar (§5.1)."""
        export = _scala_string(export_dir)
        stdout = self.execute(f"wadi.WadiPipeline.run(cpg, {export})")
        if PIPELINE_SUMMARY_MARKER not in stdout:
            raise JoernError("wadi pipeline failed inside Joern", stdout)
        return stdout

    def delete_project(self, project_name: str) -> None:
        """Dispose the project's CPG — CPGs are evictable working sets (P5)."""
        project = _scala_string(project_name)
        self.execute(f"delete({project})")


def _scala_string(value: str) -> str:
    """Render a Python string as a safe Scala string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
