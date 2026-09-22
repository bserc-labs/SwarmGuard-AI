"""scripts/deploy.sh, executed against a stub compose and a stub curl.

The stub compose records every call and remembers which tag it last brought
up; the stub curl answers healthy only if that tag is in GOOD_TAGS. So a deploy
of a bad tag fails its smoke test, and the rollback's smoke test passes, exactly
as on a real host -- which is also where this was run, against a throwaway
registry, before these tests were written.
"""

import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy.sh"
GOOD = "sha-" + "a" * 40
GOOD2 = "sha-" + "c" * 40
BAD = "sha-" + "b" * 40

COMPOSE_STUB = """#!/bin/sh
echo "compose $* TAG=${SWARMGUARD_TAG:-}" >> "$CALL_LOG"
case "$*" in
  *"up -d"*) printf '%s' "${SWARMGUARD_TAG:-}" > "$RUNNING_FILE" ;;
  *"pull"*) case " $PULL_FAIL_TAGS " in *" ${SWARMGUARD_TAG:-} "*) echo "no such tag" >&2; exit 1 ;; esac ;;
esac
exit 0
"""

CURL_STUB = """#!/bin/sh
running="$(cat "$RUNNING_FILE" 2>/dev/null || true)"
case " $GOOD_TAGS " in *" $running "*) exit 0 ;; esac
exit 22
"""


@dataclass
class Harness:
    shell: str
    state: Path
    log: Path
    running: Path
    env: dict

    def run(self, *args: str, good=(GOOD, GOOD2), pull_fail=(), **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(SCRIPT), *args],
            env={**self.env, "GOOD_TAGS": " ".join(good), "PULL_FAIL_TAGS": " ".join(pull_fail), **env},
            capture_output=True, text=True, timeout=60,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def ups(self) -> list[str]:
        return [c.rsplit("TAG=", 1)[1] for c in self.calls() if " up -d" in c]

    def current(self) -> str:
        return (self.state / "current").read_text() if (self.state / "current").exists() else ""

    def previous(self) -> str:
        return (self.state / "previous").read_text() if (self.state / "previous").exists() else ""


@pytest.fixture
def h(tmp_path) -> Harness:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no POSIX shell")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("stub-compose", COMPOSE_STUB), ("curl", CURL_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log, running, state = tmp_path / "calls.log", tmp_path / "running", tmp_path / "state"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CALL_LOG": str(log),
        "RUNNING_FILE": str(running),
        "SWARMGUARD_DEPLOY_STATE": str(state),
        "SWARMGUARD_COMPOSE": str(bin_dir / "stub-compose"),
        # Fail fast: one probe, then past the deadline.
        "SWARMGUARD_SMOKE_TIMEOUT_S": "1",
    }
    return Harness(shell, state, log, running, env)


class TestWhatMayBeDeployed:
    @pytest.mark.parametrize("tag", ["main", "latest", "v1.2", "sha"])
    def test_only_an_immutable_sha_tag(self, h, tag):
        done = h.run(tag)
        assert done.returncode == 2
        assert h.calls() == [], "nothing may be touched before the refusal"

    def test_no_argument_is_usage(self, h):
        assert h.run().returncode == 2


class TestAFirstDeploy:
    def test_pulls_then_brings_up_without_building(self, h):
        done = h.run(GOOD)
        assert done.returncode == 0, done.stderr
        pull, up = h.calls()
        assert pull.startswith("compose") and " pull" in pull and pull.endswith(f"TAG={GOOD}")
        assert " up -d --no-build" in up and up.endswith(f"TAG={GOOD}")
        assert h.current() == GOOD and h.previous() == ""

    def test_a_tag_that_does_not_exist_touches_nothing_running(self, h):
        done = h.run(GOOD, pull_fail=(GOOD,))
        assert done.returncode != 0
        assert h.ups() == [] and h.current() == ""

    def test_a_failure_with_nothing_to_roll_back_to_says_so(self, h):
        done = h.run(BAD)
        assert done.returncode == 1
        assert "no previous release" in done.stderr
        assert h.current() == ""


class TestASecondDeploy:
    def test_success_remembers_the_previous_tag(self, h):
        h.run(GOOD)
        done = h.run(GOOD2)
        assert done.returncode == 0, done.stderr
        assert h.current() == GOOD2 and h.previous() == GOOD

    def test_a_bad_release_is_rolled_back_and_still_reported_as_a_failure(self, h):
        h.run(GOOD)
        done = h.run(BAD)
        assert done.returncode == 1, "a rollback that worked is still a deploy that failed"
        assert h.ups()[-2:] == [BAD, GOOD], h.ups()
        assert "is back and healthy" in done.stderr
        assert h.current() == GOOD, "the bad tag must never be recorded as current"
        assert h.running.read_text() == GOOD

    def test_a_rollback_that_also_fails_is_reported_as_such(self, h):
        h.run(GOOD)
        done = h.run(BAD, good=())  # nothing is healthy any more
        assert done.returncode == 1
        assert "does NOT pass the smoke test after rollback" in done.stderr

    def test_deploying_the_current_tag_is_a_no_op(self, h):
        h.run(GOOD)
        before = len(h.calls())
        done = h.run(GOOD)
        assert done.returncode == 0 and "already deployed" in done.stdout
        assert len(h.calls()) == before


class TestExplicitRollback:
    def test_it_swaps_current_and_previous(self, h):
        h.run(GOOD)
        h.run(GOOD2)
        done = h.run("--rollback")
        assert done.returncode == 0, done.stderr
        assert h.ups()[-1] == GOOD
        assert h.current() == GOOD and h.previous() == GOOD2

    def test_with_nothing_to_go_back_to(self, h):
        h.run(GOOD)
        done = h.run("--rollback")
        assert done.returncode == 1 and "nothing to roll back to" in done.stderr

    def test_status_reports_both(self, h):
        h.run(GOOD)
        h.run(GOOD2)
        done = h.run("--status")
        assert f"current:  {GOOD2}" in done.stdout and f"previous: {GOOD}" in done.stdout
