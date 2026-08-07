"""Parse-root staging (§5.2.6, §5.2.14): what Joern is actually pointed at.

This is the code that assembles the CPG input. A mistake here is silent — the
frontend parses a tree that is missing types, and every downstream fact
degrades honestly rather than failing, so nothing goes red. That is exactly
how a library modelled as a peer service cost 335 response shapes without
tripping a single alarm.
"""

from pathlib import Path

from wadi_worker.boundary import DiscoveredService
from wadi_worker.pipeline import stage_parse_root


def _module(root: Path, name: str) -> None:
    source = root / "src" / "main" / "java"
    source.mkdir(parents=True, exist_ok=True)
    (source / f"{name}.java").write_text(f"class {name} {{}}")


def _service(build_root: str = ".", library_roots: list[str] | None = None) -> DiscoveredService:
    return DiscoveredService(
        name="app",
        build_root=build_root,
        build_system="maven",
        languages=["java"],
        library_roots=library_roots or [],
    )


class TestParseRoot:
    def test_no_libraries_parses_the_build_root_itself(self, tmp_path: Path) -> None:
        # No staging when there is nothing to union: the build root is handed
        # to the frontend directly, so anchors are the file's own paths.
        checkout = tmp_path / "repo"
        _module(checkout, "App")
        assert stage_parse_root(tmp_path / "ws", checkout, {}, _service(), "svc_a") == checkout

    def test_a_same_repo_library_is_staged_under_wadi_libs(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _module(checkout / "svc", "App")
        _module(checkout / "shared", "Util")
        service = _service(build_root="svc", library_roots=["shared"])

        stage = stage_parse_root(tmp_path / "ws", checkout, {}, service, "svc_a")

        assert (stage / "src" / "main" / "java" / "App.java").is_file()
        assert (stage / "wadi-libs" / "shared" / "src" / "main" / "java" / "Util.java").is_file()

    def test_a_sibling_repo_library_is_reached_through_the_checkout_map(
        self, tmp_path: Path
    ) -> None:
        # §5.2.14, and the path with no prior coverage. `repo::root` has to
        # resolve against another checkout entirely; getting it wrong stages
        # nothing and the service parses without the types it returns.
        app_checkout, lib_checkout = tmp_path / "app", tmp_path / "lib"
        _module(app_checkout, "App")
        _module(lib_checkout, "Shared")
        service = _service(library_roots=["libRepo::."])

        stage = stage_parse_root(
            tmp_path / "ws", app_checkout, {"libRepo": lib_checkout}, service, "svc_a"
        )

        assert (stage / "src" / "main" / "java" / "App.java").is_file()
        # `.` names the checkout root, so the staged dirname is the repo dir.
        staged = list((stage / "wadi-libs").rglob("Shared.java"))
        assert staged, f"library not staged; tree was {[p.name for p in stage.rglob('*')]}"

    def test_an_unknown_repo_key_falls_back_rather_than_crashing(self, tmp_path: Path) -> None:
        # A qualifier naming a repo that is not in the map must not raise —
        # the service still parses, one library short, and says so in the log.
        checkout = tmp_path / "repo"
        _module(checkout, "App")
        service = _service(library_roots=["ghost::somewhere"])

        stage = stage_parse_root(tmp_path / "ws", checkout, {}, service, "svc_a")

        assert (stage / "src" / "main" / "java" / "App.java").is_file()
        assert not (stage / "wadi-libs").exists()

    def test_two_dependents_naming_one_library_root_stage_once(self, tmp_path: Path) -> None:
        # `shared` reached twice (directly and transitively) must not make
        # copytree raise FileExistsError mid-stage.
        checkout = tmp_path / "repo"
        _module(checkout / "svc", "App")
        _module(checkout / "shared", "Util")
        service = _service(build_root="svc", library_roots=["shared", "shared"])

        stage = stage_parse_root(tmp_path / "ws", checkout, {}, service, "svc_a")

        assert (stage / "wadi-libs" / "shared" / "src" / "main" / "java" / "Util.java").is_file()

    def test_restaging_replaces_a_previous_run(self, tmp_path: Path) -> None:
        # Re-running an analysis must not union with the last one's leftovers.
        checkout = tmp_path / "repo"
        _module(checkout / "svc", "App")
        _module(checkout / "shared", "Util")
        service = _service(build_root="svc", library_roots=["shared"])
        workspace = tmp_path / "ws"

        first = stage_parse_root(workspace, checkout, {}, service, "svc_a")
        (first / "src" / "main" / "java" / "Stale.java").write_text("class Stale {}")
        second = stage_parse_root(workspace, checkout, {}, service, "svc_a")

        assert not (second / "src" / "main" / "java" / "Stale.java").exists()
