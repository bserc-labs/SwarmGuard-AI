"""scripts/purge-db-history.sh, run against a throwaway repository.

It rewrites history, so it is rehearsed here on a repository made for the
purpose: a SQLite file with a users table committed, changed and deleted, next
to ordinary files that must survive. Skipped where git-filter-repo is not
installed; the script itself refuses to run without it.
"""

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "purge-db-history.sh"
GIT = shutil.which("git") or "git"
SH = shutil.which("sh") or "/bin/sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
             "PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin"},
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    if shutil.which("git") is None or subprocess.run(  # noqa: S603 - fixed argv
        [GIT, "filter-repo", "--version"], capture_output=True
    ).returncode != 0:
        pytest.skip("needs git-filter-repo")
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    (src / "README.md").write_text("hello\n")
    db = src / "backend" / "app.db"
    db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE users (username TEXT, hashed_password TEXT)")
        conn.execute("INSERT INTO users VALUES ('admin', '$2b$12$notarealhash')")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "scaffold, database included")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO users VALUES ('pilot', '$2b$12$notarealhash')")
    (src / "README.md").write_text("hello again\n")
    _git(src, "commit", "-qam", "more users, and a real change")
    _git(src, "rm", "-q", "--cached", "backend/app.db")
    _git(src, "commit", "-qm", "untrack the database")
    return src


def test_the_blobs_are_gone_the_rest_survives_and_nothing_is_pushed(repo, tmp_path):
    work = tmp_path / "purged"
    done = subprocess.run(  # noqa: S603 - fixed argv
        [SH, str(SCRIPT), str(repo), str(work)], capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr

    assert _git(work, "log", "--all", "--format=%H", "--", "*.db") == ""
    objects = _git(work, "rev-list", "--objects", "--all")
    assert ".db" not in objects
    assert "hello again" in _git(work, "show", "main:README.md"), "ordinary history must survive"

    # The accounts to rotate are named; nothing secret is printed.
    assert "  - admin" in done.stdout and "  - pilot" in done.stdout
    assert "notarealhash" not in done.stdout
    # It prepares, it does not push: there is no remote left to push to.
    assert _git(work, "remote") == ""
    assert "NOTHING HAS BEEN PUSHED" in done.stdout
    # The source is untouched.
    assert _git(repo, "log", "--all", "--format=%H", "--", "*.db") != ""


def test_it_refuses_an_existing_workdir(repo, tmp_path):
    work = tmp_path / "exists"
    work.mkdir()
    done = subprocess.run(  # noqa: S603 - fixed argv
        [SH, str(SCRIPT), str(repo), str(work)], capture_output=True, text=True, timeout=60,
    )
    assert done.returncode != 0 and "exists" in done.stderr
