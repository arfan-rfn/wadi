"""CLI test fixtures — and a hard stop between the suite and real Docker.

`make test` deleted the developer's running stack. Not once: every run, all
session, while it was misread first as memory pressure and then as an
unexplained environment fault. The mechanism, once the events were captured
live: `wadi down` tears the stack down in three steps, and a test that invokes
it stubbed two of them.

    reap_managed_containers()   # stubbed
    run_compose(["down", …])    # stubbed
    finish_network_teardown()   # NOT stubbed — shells out to docker

That third call removes every container on the wadi network whose image is in
the release namespace, which is exactly what was observed: the five
`ghcr.io/wadi-sh/*` containers killed and destroyed within one second, `mongo`
and `neo4j` — public images, "foreign" by that function's own rule — untouched.

Stubbing that one call in the two tests that hit it would fix today's instance
and leave the trap armed, because the trap is that a CLI whose job is driving
Docker is unit-tested against the real daemon. This fixture removes the class:
`compose` cannot reach a subprocess unless a test says so explicitly, and one
that forgets fails loudly here instead of quietly on the machine.
"""

import subprocess
from typing import cast

import pytest

from wadi_cli import compose


@pytest.fixture(autouse=True)
def no_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test rather than run a docker command against the machine.

    Tests that mean to inspect the commands they would issue keep patching
    ``compose.subprocess.run`` themselves; theirs wins, because it is applied
    after this one. Nothing needs to opt in — only to be honest about it.
    """

    def refuse(
        args: object = None, *rest: object, **kwargs: object
    ) -> "subprocess.CompletedProcess[str]":
        parts = cast(list[object], args) if isinstance(args, list) else [args]
        command = " ".join(str(part) for part in parts)
        raise AssertionError(
            "a CLI test tried to run a real command: "
            f"{command!r}. Stub the compose call it comes from — this suite "
            "must never touch the machine's containers."
        )

    monkeypatch.setattr(compose.subprocess, "run", refuse)
