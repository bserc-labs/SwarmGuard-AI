"""entrypoint.sh is run for real, against stub binaries that record their calls.

The script used to migrate and then serve on every start, which is safe for
exactly one replica. It now has two modes, and what matters is which commands
each one runs, and in what order -- so that is what is asserted, by executing
it, rather than by reading its text.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"

STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$CALL_LOG"
exit "${STUB_EXIT:-0}"
"""


@pytest.fixture
def run(tmp_path):
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no POSIX shell available")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("alembic", "python", "uvicorn"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    call_log = tmp_path / "calls.log"

    def _run(*args: str, **env: str):
        call_log.write_text("")
        done = subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [shell, str(ENTRYPOINT), *args],
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CALL_LOG": str(call_log), **env},
            capture_output=True,
            text=True,
            timeout=30,
        )
        return done, call_log.read_text().splitlines()

    return _run


def _programs(calls: list[str]) -> list[str]:
    return [line.split()[0] for line in calls]


class TestServe:
    def test_it_is_the_default_and_it_does_not_migrate(self, run):
        done, calls = run()
        assert done.returncode == 0, done.stderr
        assert _programs(calls) == ["uvicorn"], calls

    def test_forwarded_headers_are_trusted_from_loopback_unless_told_otherwise(self, run):
        _, calls = run("serve")
        assert "--forwarded-allow-ips 127.0.0.1" in calls[0]
        _, calls = run("serve", FORWARDED_ALLOW_IPS="172.28.0.10")
        assert "--forwarded-allow-ips 172.28.0.10" in calls[0]

    def test_migrating_on_start_is_opt_in_and_happens_first(self, run):
        done, calls = run("serve", RUN_MIGRATIONS_ON_START="true")
        assert done.returncode == 0, done.stderr
        assert _programs(calls) == ["alembic", "uvicorn"], calls

    def test_a_failed_migration_stops_the_server_from_starting(self, run):
        done, calls = run("serve", RUN_MIGRATIONS_ON_START="true", STUB_EXIT="1")
        assert done.returncode != 0
        assert "uvicorn" not in _programs(calls)


class TestMigrate:
    def test_it_migrates_and_exits_without_serving(self, run):
        done, calls = run("migrate")
        assert done.returncode == 0, done.stderr
        assert calls == ["alembic upgrade head"], calls

    def test_it_provisions_the_admin_only_when_both_values_are_given(self, run):
        _, calls = run("migrate", ADMIN_USERNAME="root")
        assert _programs(calls) == ["alembic"], "a username alone must not provision"
        _, calls = run("migrate", ADMIN_USERNAME="root", ADMIN_PASSWORD="a-long-password")
        assert calls == ["alembic upgrade head", "python bootstrap.py"], calls

    def test_a_failed_migration_fails_the_job_and_skips_provisioning(self, run):
        """compose gates the API on this job's exit code."""
        done, calls = run("migrate", ADMIN_USERNAME="root", ADMIN_PASSWORD="pw", STUB_EXIT="1")
        assert done.returncode != 0
        assert _programs(calls) == ["alembic"], calls


def test_any_other_command_is_run_as_given(run):
    """`docker compose run --rm backend alembic current` must just work."""
    done, calls = run("alembic", "current")
    assert done.returncode == 0, done.stderr
    assert calls == ["alembic current"], calls


def test_the_script_is_executable_in_the_repository():
    assert os.access(ENTRYPOINT, os.X_OK) or "chmod +x" in (
        ENTRYPOINT.parent / "Dockerfile"
    ).read_text(), "the image must be able to execute its entrypoint"
