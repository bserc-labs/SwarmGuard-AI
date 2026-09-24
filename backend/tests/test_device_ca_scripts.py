"""scripts/device-ca.sh and frontend/nginx/41-device-ca.sh, executed for real.

The CA script is what an operator runs to give a drone its identity and to take
it away again. What matters is what `openssl verify` -- the same library nginx
uses -- makes of its output: an issued certificate chains, a revoked one does
not, and the subject names exactly one drone in one organization.

The entrypoint is what makes the device port safe by default. With nothing
mounted it must start (nginx will not run without a client CA) and admit no
one; with half a trust directory mounted it must refuse to start, because a
CA without its revocation list lets revoked drones in.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CA_SCRIPT = ROOT / "scripts" / "device-ca.sh"
ENTRYPOINT = ROOT / "frontend" / "nginx" / "41-device-ca.sh"


@dataclass
class Tools:
    shell: str
    openssl: str
    tmp: Path

    def env(self, **extra: str) -> dict[str, str]:
        return {"PATH": f"{Path(self.openssl).parent}:/usr/bin:/bin", **extra}

    def ca(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(CA_SCRIPT), *args],
            env=self.env(SWARMGUARD_DEVICE_CA_HOME=str(self.tmp / "ca")),
            capture_output=True, text=True, timeout=60,
        )

    def entrypoint(self, mounted: Path, active: Path) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.shell, str(ENTRYPOINT)],
            env=self.env(DEVICE_CA_DIR=str(mounted), TLS_ACTIVE_DIR=str(active)),
            capture_output=True, text=True, timeout=60,
        )

    def verify(self, ca: Path, crl: Path, cert: Path) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.openssl, "verify", "-CAfile", str(ca), "-crl_check", "-CRLfile", str(crl), str(cert)],
            capture_output=True, text=True,
        )

    def subject(self, cert: Path) -> str:
        return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [self.openssl, "x509", "-in", str(cert), "-noout", "-subject", "-nameopt", "RFC2253"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    @property
    def trust(self) -> Path:
        return self.tmp / "ca" / "trust"

    def issued(self, org: int, drone: str) -> Path:
        (directory,) = (self.tmp / "ca" / "issued" / f"org-{org}").glob(f"{drone}-*")
        return directory


@pytest.fixture
def tools(tmp_path) -> Tools:
    shell, openssl = shutil.which("sh"), shutil.which("openssl")
    if shell is None or openssl is None:
        pytest.skip("needs a POSIX shell and openssl")
    return Tools(shell, openssl, tmp_path)


@pytest.fixture
def ca(tools) -> Tools:
    done = tools.ca("init")
    assert done.returncode == 0, done.stderr
    return tools


class TestTheCa:
    def test_an_issued_certificate_chains_and_names_one_drone(self, ca):
        done = ca.ca("issue", "3", "drone-7")
        assert done.returncode == 0, done.stderr
        cert = ca.issued(3, "drone-7") / "device.crt"
        assert ca.verify(ca.trust / "ca.crt", ca.trust / "crl.pem", cert).returncode == 0
        # The form nginx forwards as $ssl_client_s_dn, and the API compares.
        assert ca.subject(cert) == "subject=CN=drone-7,O=org:3"

    def test_it_is_for_client_authentication_only(self, ca):
        ca.ca("issue", "3", "drone-7")
        text = subprocess.run(  # noqa: S603
            [ca.openssl, "x509", "-in", str(ca.issued(3, "drone-7") / "device.crt"), "-noout", "-text"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "TLS Web Client Authentication" in text
        assert "CA:FALSE" in text

    def test_a_revoked_certificate_no_longer_verifies(self, ca):
        ca.ca("issue", "3", "drone-7")
        ca.ca("issue", "3", "drone-8")
        revoked = ca.issued(3, "drone-7") / "device.crt"
        done = ca.ca("revoke", str(revoked))
        assert done.returncode == 0, done.stderr
        failed = ca.verify(ca.trust / "ca.crt", ca.trust / "crl.pem", revoked)
        assert failed.returncode != 0 and "revoked" in (failed.stdout + failed.stderr)
        # Revoking one drone leaves the fleet alone.
        other = ca.issued(3, "drone-8") / "device.crt"
        assert ca.verify(ca.trust / "ca.crt", ca.trust / "crl.pem", other).returncode == 0
        assert "REVOKED" in ca.ca("list").stdout

    def test_the_proxy_half_holds_no_private_key(self, ca):
        assert sorted(p.name for p in ca.trust.iterdir()) == ["ca.crt", "crl.pem"]

    def test_the_ca_key_is_readable_by_its_owner_only(self, ca):
        key = ca.tmp / "ca" / "private" / "ca.key"
        assert key.stat().st_mode & 0o077 == 0
        assert (ca.tmp / "ca" / "private").stat().st_mode & 0o077 == 0

    def test_init_refuses_to_replace_a_ca(self, ca):
        done = ca.ca("init")
        assert done.returncode != 0 and "refusing" in done.stderr

    @pytest.mark.parametrize("drone", ["a,b", "x/../y", "CN=evil", ""])
    def test_a_drone_id_cannot_inject_into_the_subject_or_the_path(self, ca, drone):
        assert ca.ca("issue", "3", drone).returncode != 0

    def test_the_organization_must_be_a_number(self, ca):
        assert ca.ca("issue", "org:3", "drone-7").returncode != 0


class TestTheEntrypoint:
    def test_a_mounted_trust_directory_is_linked(self, ca):
        active = ca.tmp / "active"
        done = ca.entrypoint(ca.trust, active)
        assert done.returncode == 0, done.stderr
        assert (active / "device-ca.crt").resolve() == (ca.trust / "ca.crt").resolve()
        assert (active / "device-crl.pem").resolve() == (ca.trust / "crl.pem").resolve()
        assert "CRL valid until" in done.stdout

    @pytest.mark.parametrize("present", ["ca.crt", "crl.pem"])
    def test_half_is_an_error(self, ca, present):
        half = ca.tmp / "half"
        half.mkdir()
        shutil.copy(ca.trust / present, half / present)
        done = ca.entrypoint(half, ca.tmp / "active")
        assert done.returncode != 0
        assert "both ca.crt and crl.pem" in done.stderr

    def test_a_crl_from_another_ca_is_refused(self, ca, tmp_path):
        other = Tools(ca.shell, ca.openssl, tmp_path / "other")
        (tmp_path / "other").mkdir()
        assert other.ca("init").returncode == 0
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        shutil.copy(ca.trust / "ca.crt", mixed / "ca.crt")
        shutil.copy(other.trust / "crl.pem", mixed / "crl.pem")
        done = ca.entrypoint(mixed, tmp_path / "active")
        assert done.returncode != 0 and "not a revocation list signed by" in done.stderr

    def test_with_nothing_mounted_the_port_admits_no_one(self, ca):
        empty, active = ca.tmp / "empty", ca.tmp / "active"
        empty.mkdir()
        done = ca.entrypoint(empty, active)
        assert done.returncode == 0, done.stderr
        assert "refuse" in done.stdout
        # nginx starts: both files exist, and the CRL is signed by the CA...
        assert (active / "device-ca.crt").is_file() and not (active / "device-ca.crt").is_symlink()
        assert (active / "device-crl.pem").is_file()
        # ...and a genuine device certificate from a real CA does not chain to it.
        ca.ca("issue", "3", "drone-7")
        cert = ca.issued(3, "drone-7") / "device.crt"
        assert ca.verify(active / "device-ca.crt", active / "device-crl.pem", cert).returncode != 0
        # No private key was left behind for anyone to sign with.
        assert not list(active.glob("*.key"))
