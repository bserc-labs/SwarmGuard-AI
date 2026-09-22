"""scripts/backup.sh, restore.sh and check-backups.sh, executed for real.

pg_dump, pg_restore and psql are stubs that record what they were asked to do,
so the assertions are about behaviour -- what ran, in what order, with which
flags, and what was left on disk -- rather than about the text of the scripts.
The scripts are also exercised against a real database: by CI on every push
(rehearse-restore.sh in the live-suite job) and by hand on the development
stack, where a live restore was run and every table compared.
"""

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# Records `<program> <args>` and, for pg_dump, writes the file it was told to.
STUB = """#!/bin/sh
name=$(basename "$0")
echo "$name $*" >> "$CALL_LOG"
[ -n "$PGPASSWORD" ] && echo "PGPASSWORD=$PGPASSWORD" >> "$CALL_LOG"
[ "${FAIL_PROGRAM:-}" = "$name" ] && exit 1
if [ "$name" = pg_dump ]; then
  while [ $# -gt 0 ]; do [ "$1" = -f ] && printf 'DUMP-BYTES' > "$2"; shift; done
fi
exit 0
"""


@dataclass
class Harness:
    shell: str
    bin: Path
    backups: Path
    log: Path
    env: dict = field(default_factory=dict)

    def run(self, script: str, *args: str, timeout: float = 30, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(SCRIPTS / script), *args],
            env=self._env(env), capture_output=True, text=True, timeout=timeout,
        )

    def start(self, script: str, *args: str, **env: str) -> subprocess.Popen:
        return subprocess.Popen(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(SCRIPTS / script), *args],
            env=self._env(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def _env(self, extra: dict) -> dict:
        return {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALL_LOG": str(self.log),
            "BACKUP_DIR": str(self.backups),
            "PGDATABASE": "swarmguard",
            **self.env, **extra,
        }

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def programs(self) -> list[str]:
        return [c.split()[0] for c in self.calls() if not c.startswith("PGPASSWORD=")]

    def dumps(self) -> list[str]:
        return sorted(p.name for p in self.backups.glob("*.dump"))


@pytest.fixture
def h(tmp_path) -> Harness:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no POSIX shell")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pg_dump", "pg_restore", "psql"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    backups = tmp_path / "backups"
    backups.mkdir()
    return Harness(shell, bin_dir, backups, tmp_path / "calls.log")


def _age(path: Path, days: float) -> None:
    then = time.time() - days * 86400
    os.utime(path, (then, then))


class TestBackup:
    def test_once_writes_a_timestamped_complete_dump(self, h):
        done = h.run("backup.sh", "--once")
        assert done.returncode == 0, done.stderr
        (name,) = h.dumps()
        assert name.startswith("swarmguard-") and name.endswith("Z.dump")
        assert (h.backups / name).read_text() == "DUMP-BYTES"
        assert not list(h.backups.glob("*.partial")), "a finished dump must not leave its temp name"
        assert "wrote" in done.stdout
        assert "-Fc" in h.calls()[0], "custom format: compressed, and restorable table by table"

    def test_a_failed_dump_leaves_nothing_that_looks_like_a_backup(self, h):
        done = h.run("backup.sh", "--once", FAIL_PROGRAM="pg_dump")
        assert done.returncode == 1
        assert h.dumps() == [] and not list(h.backups.glob("*.partial"))
        assert "ERROR" in done.stderr

    def test_the_password_comes_from_the_secret_file(self, h, tmp_path):
        secret = tmp_path / "pw"
        secret.write_text("from-the-file")
        h.run("backup.sh", "--once", PGPASSWORD_FILE=str(secret))
        assert "PGPASSWORD=from-the-file" in h.calls()

    def test_prune_removes_only_our_old_complete_dumps(self, h):
        old = h.backups / "swarmguard-20200101T000000Z.dump"
        recent = h.backups / "swarmguard-20260101T000000Z.dump"
        partial = h.backups / "swarmguard-20200102T000000Z.dump.partial"
        foreign = h.backups / "somebody-elses.dump"
        for f in (old, recent, partial, foreign):
            f.write_text("x")
        _age(old, 20)
        _age(partial, 20)
        _age(foreign, 20)
        done = h.run("backup.sh", "--once", BACKUP_RETAIN_DAYS="14")
        assert done.returncode == 0, done.stderr
        assert not old.exists() and "pruned" in done.stdout
        assert recent.exists() and partial.exists() and foreign.exists()

    def test_the_loop_survives_a_failed_dump_and_tries_again(self, h):
        """A container that exits on the first failure is one that stops trying."""
        proc = h.start("backup.sh", BACKUP_INTERVAL_S="1", FAIL_PROGRAM="pg_dump")
        try:
            time.sleep(2.7)
            assert proc.poll() is None, "the loop exited"
        finally:
            proc.kill()
            proc.wait(timeout=5)
        assert h.programs().count("pg_dump") >= 2


class TestRestore:
    def _dump(self, h, name="swarmguard-20260101T000000Z.dump") -> Path:
        path = h.backups / name
        path.write_text("DUMP-BYTES")
        return path

    def test_it_refuses_the_live_database_without_consent(self, h):
        self._dump(h)
        done = h.run("restore.sh")
        assert done.returncode == 1
        assert "--yes" in done.stderr
        assert h.programs() == [], "nothing may be touched before the refusal"

    def test_it_refuses_an_unfinished_dump(self, h):
        partial = h.backups / "swarmguard-x.dump.partial"
        partial.write_text("half")
        done = h.run("restore.sh", "--dump", str(partial), "--into", "scratch")
        assert done.returncode == 1 and h.programs() == []

    def test_no_dump_at_all_is_an_error_not_an_empty_restore(self, h):
        done = h.run("restore.sh", "--into", "scratch")
        assert done.returncode == 1 and "no dump" in done.stderr

    def test_it_picks_the_newest_dump_by_default(self, h):
        self._dump(h, "swarmguard-20250101T000000Z.dump")
        newest = self._dump(h, "swarmguard-20260101T000000Z.dump")
        done = h.run("restore.sh", "--into", "scratch")
        assert done.returncode == 0, done.stderr
        assert any(c.startswith("pg_restore") and str(newest) in c for c in h.calls())

    def test_the_timescaledb_dance_in_order(self, h):
        dump = self._dump(h)
        done = h.run("restore.sh", "--dump", str(dump), "--into", "scratch")
        assert done.returncode == 0, done.stderr
        steps = [c for c in h.calls() if not c.startswith("PGPASSWORD=")]
        assert [s.split()[0] for s in steps] == ["psql", "psql", "psql", "psql", "pg_restore", "psql"]
        drop, create, extension, pre, restore, post = steps
        assert 'DROP DATABASE IF EXISTS "scratch" WITH (FORCE)' in drop and "-d postgres" in drop
        assert 'CREATE DATABASE "scratch"' in create
        assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in extension and "-d scratch" in extension
        assert "timescaledb_pre_restore" in pre
        assert "-d scratch" in restore and "--exit-on-error" in restore and str(dump) in restore
        assert "timescaledb_post_restore" in post
        for step in (drop, create, extension, pre, post):
            assert "ON_ERROR_STOP=1" in step, "a failing step must stop the restore"

    def test_a_failed_scratch_restore_is_dropped_not_left_half_built(self, h):
        dump = self._dump(h)
        done = h.run("restore.sh", "--dump", str(dump), "--into", "scratch", FAIL_PROGRAM="pg_restore")
        assert done.returncode == 1
        assert "dropped" in done.stderr
        after_failure = h.calls()[h.calls().index(next(c for c in h.calls() if c.startswith("pg_restore"))) + 1:]
        assert any('DROP DATABASE IF EXISTS "scratch"' in c for c in after_failure)
        assert not any("timescaledb_post_restore" in c for c in after_failure)

    def test_a_failed_live_restore_is_reported_as_incomplete_and_kept(self, h):
        """There may be nothing better to replace it with; say so instead of deleting it."""
        dump = self._dump(h)
        done = h.run("restore.sh", "--dump", str(dump), "--yes", FAIL_PROGRAM="pg_restore")
        assert done.returncode == 1
        assert "INCOMPLETE" in done.stderr
        after_failure = h.calls()[h.calls().index(next(c for c in h.calls() if c.startswith("pg_restore"))) + 1:]
        assert not any("DROP DATABASE" in c for c in after_failure)


class TestCheckBackups:
    def _named(self, h, stamp: str, size: int = 4096) -> Path:
        path = h.backups / f"swarmguard-{stamp}Z.dump"
        path.write_bytes(b"x" * size)
        return path

    def _now_stamp(self, offset_s: int = 0) -> str:
        return time.strftime("%Y%m%dT%H%M%S", time.gmtime(time.time() - offset_s))

    def test_no_backups_fails(self, h):
        done = h.run("check-backups.sh")
        assert done.returncode == 1 and "NO BACKUPS" in done.stdout

    def test_a_fresh_dump_passes(self, h):
        self._named(h, self._now_stamp(60))
        done = h.run("check-backups.sh", BACKUP_INTERVAL_S="21600")
        assert done.returncode == 0, done.stdout
        assert done.stdout.startswith("OK")

    def test_one_missed_run_is_tolerated_and_two_are_not(self, h):
        self._named(h, self._now_stamp(int(1.5 * 3600)))
        assert h.run("check-backups.sh", BACKUP_INTERVAL_S="3600").returncode == 0
        h.backups.joinpath(h.dumps()[0]).unlink()
        self._named(h, self._now_stamp(int(2.5 * 3600)))
        done = h.run("check-backups.sh", BACKUP_INTERVAL_S="3600")
        assert done.returncode == 1 and "STALE" in done.stdout

    def test_it_judges_the_newest_not_the_oldest(self, h):
        self._named(h, "20200101T000000")
        self._named(h, self._now_stamp(60))
        assert h.run("check-backups.sh").returncode == 0

    def test_a_tiny_dump_is_suspicious(self, h):
        """pg_dump against an empty or wrong database still produces a valid, useless file."""
        self._named(h, self._now_stamp(60), size=200)
        done = h.run("check-backups.sh")
        assert done.returncode == 1 and "SUSPICIOUS" in done.stdout

    def test_an_unfinished_dump_does_not_count(self, h):
        (h.backups / f"swarmguard-{self._now_stamp()}Z.dump.partial").write_bytes(b"x" * 4096)
        done = h.run("check-backups.sh")
        assert done.returncode == 1 and "NO BACKUPS" in done.stdout
