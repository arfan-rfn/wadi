"""Orchestrator API test fixtures: real Mongo + real local git repo + ASGI client."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from orchestrator_support import make_settings, run_git

from wadi_orchestrator.app import create_app
from wadi_orchestrator.state import AppState
from wadi_storage import WadiDatabase

_git = run_git


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A local git repo acting as a system's source repository."""
    repo = tmp_path / "sample-repo"
    (repo / "src").mkdir(parents=True)
    _git("init", "--initial-branch=main", cwd=repo)
    (repo / "pom.xml").write_text("<project/>\n")
    (repo / "src" / "App.java").write_text("class App {\n  int x;\n  int y;\n}\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    return repo


@pytest.fixture
async def client(database: WadiDatabase, tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """ASGI test client against an app wired to the test database (no monitor loop)."""
    app = create_app(make_settings(tmp_path), database=database, run_monitor=False)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http,
        app.router.lifespan_context(app),
    ):
        yield http


@pytest.fixture
def app_state(client: AsyncClient, request: pytest.FixtureRequest) -> AppState:
    """The AppState of the app behind ``client`` (for driving the monitor in tests)."""
    # The client fixture stores the app on its transport.
    transport = client._transport  # pyright: ignore[reportPrivateUsage]
    assert isinstance(transport, ASGITransport)
    app = transport.app
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    state: AppState = app.state.wadi
    return state
