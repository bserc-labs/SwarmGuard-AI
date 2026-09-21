"""docker-compose.yml is deployment code, so its security-relevant shape is
pinned here. Each of these regressions shipped once:

- the backend published on 0.0.0.0:8000, a second ingress that skipped nginx;
- uvicorn trusting X-Forwarded-For from any peer (``*``), which let a client
  pick its own address for the login rate limit and the audit trail;
- tuning variables set in .env never reaching the container (no env_file);
- healthchecks with no start_period, so a slow first migration marked the
  backend unhealthy and the frontend never started.

The file is read as YAML rather than through ``docker compose config`` so the
check needs no Docker in CI. PyYAML is installed by uvicorn[standard].
"""

import ipaddress
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
ENTRYPOINT = ROOT / "backend" / "entrypoint.sh"

# ``${VAR:-default}`` -> default. Anything else is returned unchanged.
_DEFAULT = re.compile(r"^\$\{[A-Z0-9_]+:-(?P<default>[^}]*)\}$")


def _default(value: object) -> str:
    """The value compose resolves to when the interpolated variable is unset."""
    match = _DEFAULT.match(str(value))
    return match.group("default") if match else str(value)


@pytest.fixture(scope="module")
def compose() -> dict:
    with COMPOSE.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def backend(compose) -> dict:
    return compose["services"]["backend"]


@pytest.fixture(scope="module")
def proxy_ip(backend) -> str:
    return _default(backend["environment"]["FORWARDED_ALLOW_IPS"])


@pytest.fixture(scope="module")
def subnet(compose) -> ipaddress.IPv4Network:
    cfg = compose["networks"]["default"]["ipam"]["config"][0]
    return ipaddress.ip_network(_default(cfg["subnet"]))


class TestIngress:
    def test_the_api_is_published_on_loopback_only(self, backend):
        """A bare ``8000:8000`` binds every interface and bypasses nginx."""
        for entry in backend["ports"]:
            if isinstance(entry, dict):
                assert entry.get("host_ip") == "127.0.0.1", entry
            else:
                assert str(entry).startswith("127.0.0.1:"), entry

    def test_only_the_frontend_and_the_loopback_api_publish_ports(self, compose):
        publishers = {name for name, svc in compose["services"].items() if "ports" in svc}
        assert publishers == {"backend", "frontend"}, publishers


class TestForwardedHeaders:
    def test_uvicorn_trusts_forwarded_headers_only_from_the_nginx_container(
        self, compose, backend, proxy_ip, subnet
    ):
        raw_backend = backend["environment"]["FORWARDED_ALLOW_IPS"]
        raw_frontend = compose["services"]["frontend"]["networks"]["default"]["ipv4_address"]
        # Same anchor in both places, so they cannot drift.
        assert raw_backend == raw_frontend, (raw_backend, raw_frontend)

        assert proxy_ip != "*", "trust-all is the defect this test exists to prevent"
        address = ipaddress.ip_address(proxy_ip)  # a bare IP, not a CIDR
        assert address in subnet, f"{address} is outside {subnet}"
        gateway = next(subnet.hosts())
        assert address != gateway, (
            "the first address is the gateway, where every host-originated "
            "connection arrives from; trusting it re-opens the hole"
        )

    def test_uvicorn_ignores_a_client_supplied_forwarded_for(self, proxy_ip, subnet):
        """Exercise the installed uvicorn, not a re-implementation of it."""
        from uvicorn.middleware.proxy_headers import _TrustedHosts

        trusted = _TrustedHosts(proxy_ip)
        gateway = str(next(subnet.hosts()))

        assert proxy_ip in trusted
        assert gateway not in trusted

        # nginx appends the real peer after whatever the client wrote. Walking
        # from the end, the first untrusted hop is the real peer.
        assert trusted.get_trusted_client_address("1.2.3.4, 203.0.113.5") == ("203.0.113.5", 0)
        # Host-originated traffic arrives from the gateway: still untrusted,
        # so the injected 1.2.3.4 is ignored and the gateway itself is the client.
        assert trusted.get_trusted_client_address(f"1.2.3.4, {gateway}") == (gateway, 0)

    def test_the_entrypoint_fallback_is_not_the_wildcard(self):
        source = ENTRYPOINT.read_text()
        match = re.search(r'--forwarded-allow-ips\s+"\$\{FORWARDED_ALLOW_IPS:-(?P<fallback>[^}]*)\}"', source)
        assert match, "entrypoint.sh must pass --forwarded-allow-ips with a default"
        fallback = match.group("fallback")
        assert fallback != "*"
        ipaddress.ip_address(fallback)  # raises on anything but a bare IP


class TestEnvironmentPassthrough:
    def test_dot_env_reaches_the_backend_and_cannot_override_the_network_urls(self, backend):
        entries = backend.get("env_file")
        assert entries, "backend needs env_file so GUARD_*/AI_INCIDENTS_ENABLED/... reach the container"
        if isinstance(entries, str):
            entries = [entries]
        paths = {e["path"] if isinstance(e, dict) else e for e in entries}
        assert ".env" in paths, paths

        # These must stay under `environment:`, which takes precedence over
        # env_file, or the native-run values in .env would point the container
        # at localhost.
        env = backend["environment"]
        assert "@postgres:5432/" in env["DATABASE_URL"]
        assert env["REDIS_URL"].startswith("redis://redis:")
        assert "FORWARDED_ALLOW_IPS" in env


class TestHealthchecks:
    def test_every_healthcheck_declares_a_start_period(self, compose):
        missing = [
            name
            for name, svc in compose["services"].items()
            if "healthcheck" in svc and "start_period" not in svc["healthcheck"]
        ]
        assert not missing, f"no start_period: {missing}"

    def test_the_postgres_probe_uses_tcp(self, compose):
        test = compose["services"]["postgres"]["healthcheck"]["test"]
        command = " ".join(test) if isinstance(test, list) else str(test)
        assert "pg_isready" in command and "-h 127.0.0.1" in command, command
