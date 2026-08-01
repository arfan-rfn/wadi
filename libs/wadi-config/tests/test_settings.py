"""Settings tests: env override, .env files, defaults, validation, secrecy."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from wadi_config import WadiSettings, get_settings


@pytest.fixture(autouse=True)
def clean_wadi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests control WADI_* env explicitly; a developer's real env must not leak in."""
    import os

    for key in list(os.environ):
        if key.startswith("WADI_"):
            monkeypatch.delenv(key)
    get_settings.cache_clear()


def _settings(**kwargs: object) -> WadiSettings:
    # _env_file=None disables .env pickup so tests are hermetic wherever they run.
    return WadiSettings(_env_file=None, **kwargs)  # type: ignore[arg-type]


class TestDefaults:
    def test_local_stack_defaults(self) -> None:
        settings = _settings()
        assert settings.mongo_uri == "mongodb://mongo:27017"
        assert settings.api_port == 9234
        assert settings.ui_port == 9235
        assert settings.fetch_dependencies is False  # §12: off by default

    def test_frozen(self) -> None:
        settings = _settings()
        with pytest.raises(ValidationError):
            settings.api_port = 1234  # type: ignore[misc]


class TestEnvOverride:
    def test_env_var_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WADI_MONGO_URI", "mongodb+srv://user:pw@cluster.mongodb.net")
        monkeypatch.setenv("WADI_API_PORT", "19234")
        settings = _settings()
        assert settings.mongo_uri == "mongodb+srv://user:pw@cluster.mongodb.net"
        assert settings.api_port == 19234

    def test_invalid_port_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WADI_API_PORT", "99999")
        with pytest.raises(ValidationError):
            _settings()

    def test_unrelated_wadi_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WADI_SOME_FUTURE_FLAG", "yes")
        assert _settings().api_port == 9234

    def test_paths_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WADI_WORKSPACE_DIR", "/mnt/shared/workspace")
        assert _settings().workspace_dir == Path("/mnt/shared/workspace")


class TestDotEnv:
    def test_env_file_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("WADI_MONGO_DATABASE=wadi_test\nWADI_JOB_LEASE_SECONDS=120\n")
        settings = WadiSettings(_env_file=env_file)  # type: ignore[call-arg]
        assert settings.mongo_database == "wadi_test"
        assert settings.job_lease_seconds == 120

    def test_real_env_beats_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("WADI_MONGO_DATABASE=from_file\n")
        monkeypatch.setenv("WADI_MONGO_DATABASE", "from_env")
        settings = WadiSettings(_env_file=env_file)  # type: ignore[call-arg]
        assert settings.mongo_database == "from_env"


class TestSecrets:
    def test_secrets_do_not_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WADI_API_TOKEN", "super-secret-token")
        monkeypatch.setenv("WADI_NEO4J_PASSWORD", "hunter2")
        settings = _settings()
        assert settings.api_token is not None
        text = repr(settings) + settings.model_dump_json()
        assert "super-secret-token" not in text
        assert "hunter2" not in text
        assert settings.api_token.get_secret_value() == "super-secret-token"


class TestGetSettings:
    def test_cached_singleton(self) -> None:
        assert get_settings() is get_settings()

    def test_cache_clear_rereads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = get_settings()
        assert first.mongo_database == "wadi"
        monkeypatch.setenv("WADI_MONGO_DATABASE", "other")
        get_settings.cache_clear()
        assert get_settings().mongo_database == "other"
