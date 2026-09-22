"""frontend/nginx/40-tls.sh, executed for real.

The case that matters most is the quiet one: an operator installs half a
certificate pair, the script falls back to a self-signed certificate, the site
comes up with HTTPS and a browser warning nobody reads, and everyone believes
the real certificate is in use. Half a pair must be an error.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "frontend" / "nginx" / "40-tls.sh"


@dataclass
class Harness:
    shell: str
    openssl: str
    mounted: Path  # stands in for /etc/nginx/certs, what the operator mounts
    active: Path  # stands in for /etc/nginx/tls, what nginx.conf points at

    def run(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(SCRIPT)],
            env={
                "PATH": f"{Path(self.openssl).parent}:/usr/bin:/bin",
                "TLS_CERT_DIR": str(self.mounted),
                "TLS_ACTIVE_DIR": str(self.active),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

    def describe(self, certificate: Path) -> str:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.openssl, "x509", "-in", str(certificate), "-noout", "-subject", "-ext", "subjectAltName"],
            capture_output=True, text=True, check=True,
        ).stdout


@pytest.fixture
def tls(tmp_path) -> Harness:
    shell, openssl = shutil.which("sh"), shutil.which("openssl")
    if shell is None or openssl is None:
        pytest.skip("needs a POSIX shell and openssl")
    mounted = tmp_path / "certs"
    mounted.mkdir()
    return Harness(shell, openssl, mounted, tmp_path / "tls")


class TestAMountedCertificate:
    def test_it_is_linked_not_copied(self, tls):
        """No second copy of the private key, and a renewal needs only a reload."""
        (tls.mounted / "tls.crt").write_text("CERT")
        (tls.mounted / "tls.key").write_text("KEY")
        done = tls.run()
        assert done.returncode == 0, done.stderr
        assert (tls.active / "tls.key").is_symlink()
        assert (tls.active / "tls.key").resolve() == (tls.mounted / "tls.key").resolve()
        assert (tls.active / "tls.crt").read_text() == "CERT"
        assert "SELF-SIGNED" not in done.stdout

    @pytest.mark.parametrize("present", ["tls.crt", "tls.key"])
    def test_half_a_pair_is_an_error_not_a_reason_to_self_sign(self, tls, present):
        (tls.mounted / present).write_text("X")
        done = tls.run()
        assert done.returncode != 0
        assert "both tls.crt and tls.key" in done.stderr
        assert not list(tls.active.glob("tls.*")), "nothing may be left for nginx to start with"

    def test_an_empty_file_counts_as_missing(self, tls):
        (tls.mounted / "tls.crt").write_text("CERT")
        (tls.mounted / "tls.key").write_text("")
        assert tls.run().returncode != 0

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
    def test_a_key_nginx_cannot_read_is_reported_as_such(self, tls):
        """nginx runs unprivileged; its own error for this is far less clear."""
        (tls.mounted / "tls.crt").write_text("CERT")
        key = tls.mounted / "tls.key"
        key.write_text("KEY")
        key.chmod(0o000)
        try:
            done = tls.run()
        finally:
            key.chmod(0o600)
        assert done.returncode != 0
        assert "not readable" in done.stderr


class TestTheSelfSignedFallback:
    def test_it_generates_a_usable_pair_and_says_so_loudly(self, tls):
        done = tls.run()
        assert done.returncode == 0, done.stderr
        assert "SELF-SIGNED" in done.stdout and "WARNING" in done.stdout
        assert "BEGIN CERTIFICATE" in (tls.active / "tls.crt").read_text()
        assert "PRIVATE KEY" in (tls.active / "tls.key").read_text()
        assert not (tls.active / "tls.key").is_symlink()

    def test_the_private_key_is_not_readable_by_anyone_else(self, tls):
        tls.run()
        assert (tls.active / "tls.key").stat().st_mode & 0o077 == 0

    def test_it_is_valid_for_localhost_and_loopback(self, tls):
        tls.run()
        details = tls.describe(tls.active / "tls.crt")
        assert "CN=localhost" in details.replace(" ", "")
        assert "127.0.0.1" in details
        assert details.count("DNS:localhost") == 1

    def test_a_hostname_is_added_without_losing_localhost(self, tls):
        tls.run(TLS_SELF_SIGNED_CN="swarmguard.example.org")
        details = tls.describe(tls.active / "tls.crt")
        assert "DNS:swarmguard.example.org" in details and "DNS:localhost" in details

    def test_stale_links_from_an_earlier_mount_are_replaced(self, tls):
        """The certificate directory was mounted once, then removed."""
        tls.active.mkdir()
        for name in ("tls.crt", "tls.key"):
            (tls.active / name).symlink_to(tls.mounted / name)  # dangling
        done = tls.run()
        assert done.returncode == 0, done.stderr
        assert "BEGIN CERTIFICATE" in (tls.active / "tls.crt").read_text()
        assert not (tls.mounted / "tls.crt").exists(), "must not write through a stale link"
