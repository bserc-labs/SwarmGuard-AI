"""scripts/init-secrets.sh, executed for real in a temporary directory.

The script stands between an operator and a stack that will not start, and
between an existing deployment and a database it can no longer log in to: if it
generated a fresh postgres password while the volume was initialised with the
old one, or overwrote SECRET_KEY, the damage is done before anyone reads a log.
So the properties that matter are asserted by running it.
"""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "init-secrets.sh"
REQUIRED = ("secret_key", "drone_api_key", "postgres_password")


@pytest.fixture
def run(tmp_path):
    shell = shutil.which("sh")
    if shell is None or shutil.which("openssl") is None:
        pytest.skip("needs a POSIX shell and openssl")
    secrets_dir = tmp_path / "secrets"
    env_file = tmp_path / ".env"

    def _run(*args: str, dotenv: str | None = None):
        if dotenv is not None:
            env_file.write_text(dotenv)
        done = subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [shell, str(SCRIPT), *args],
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                "SWARMGUARD_SECRETS_DIR": str(secrets_dir),
                "SWARMGUARD_ENV_FILE": str(env_file),
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        return done, secrets_dir

    return _run


def test_it_generates_what_is_missing(run):
    done, secrets = run()
    assert done.returncode == 0, done.stderr
    for name in REQUIRED:
        value = (secrets / name).read_text()
        assert len(value) == 64 and int(value, 16) >= 0, name
        assert not value.endswith("\n"), "a trailing newline would become part of the secret"
    assert len({(secrets / n).read_text() for n in REQUIRED}) == 3, "each secret must be distinct"


def test_no_admin_password_means_an_empty_file_not_a_generated_one(run):
    """Empty is how the migrate job is told not to provision an admin."""
    _, secrets = run()
    assert (secrets / "admin_password").read_text() == ""


def test_an_existing_deployment_keeps_its_values(run):
    """The postgres volume was initialised with this password; a new one locks the API out."""
    dotenv = (
        "POSTGRES_USER=swarm\n"
        "POSTGRES_PASSWORD=the-one-the-volume-knows\n"
        'SECRET_KEY="quoted-0123456789abcdef0123456789abcdef"\n'
        "DRONE_API_KEY=has=equals-0123456789abcdef0123456789abcdef   \n"
        "ADMIN_PASSWORD='single quoted pw'\n"
    )
    done, secrets = run(dotenv=dotenv)
    assert done.returncode == 0, done.stderr
    assert (secrets / "postgres_password").read_text() == "the-one-the-volume-knows"
    assert (secrets / "secret_key").read_text() == "quoted-0123456789abcdef0123456789abcdef"
    assert (secrets / "drone_api_key").read_text() == "has=equals-0123456789abcdef0123456789abcdef"
    assert (secrets / "admin_password").read_text() == "single quoted pw"


def test_the_values_are_never_printed(run):
    done, _ = run(dotenv="POSTGRES_PASSWORD=do-not-print-me-0123456789\n")
    assert "do-not-print-me" not in done.stdout + done.stderr


def test_it_never_overwrites(run):
    _, secrets = run()
    before = {n: (secrets / n).read_text() for n in REQUIRED}
    done, _ = run(dotenv="SECRET_KEY=a-different-value-0123456789abcdef0123456789\n")
    assert done.returncode == 0, done.stderr
    assert {n: (secrets / n).read_text() for n in REQUIRED} == before
    assert "Nothing to create" in done.stdout


def test_an_admin_password_added_later_is_picked_up(run):
    """The empty placeholder is read-only; a re-run must still be able to fill it."""
    _, secrets = run()
    done, _ = run(dotenv="ADMIN_PASSWORD=added-afterwards\n")
    assert done.returncode == 0, done.stderr
    assert (secrets / "admin_password").read_text() == "added-afterwards"


def test_the_directory_is_private_and_the_files_are_readable_by_containers(run):
    """Containers read these as users whose uid does not exist on the host."""
    _, secrets = run()
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o700
    for name in (*REQUIRED, "admin_password"):
        assert stat.S_IMODE((secrets / name).stat().st_mode) == 0o444, name


class TestCheckMode:
    def test_it_reports_what_is_missing_and_changes_nothing(self, run):
        done, secrets = run("--check")
        assert done.returncode == 1
        for name in REQUIRED:
            assert name in done.stdout
        assert not secrets.exists()

    def test_it_passes_once_the_secrets_exist(self, run):
        run()
        done, _ = run("--check")
        assert done.returncode == 0, done.stdout

    def test_a_secret_the_api_would_refuse_is_caught_here(self, run):
        done, _ = run(dotenv="SECRET_KEY=too-short\n")
        assert done.returncode == 1
        assert "TOO SHORT" in done.stdout
