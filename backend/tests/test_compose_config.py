"""docker-compose.yml is deployment code, so its security-relevant shape is
pinned here. Each of these regressions shipped once:

- the backend published on 0.0.0.0:8000, a second ingress that skipped nginx;
- uvicorn trusting X-Forwarded-For from any peer (``*``), which let a client
  pick its own address for the login rate limit and the audit trail;
- tuning variables set in .env never reaching the container (no env_file);
- healthchecks with no start_period, so a slow first migration marked the
  backend unhealthy and the frontend never started.
- migrations run from the backend entrypoint on every start, so two replicas
  starting together ran the same DDL against the same database at once.
- SECRET_KEY, DRONE_API_KEY and the database password passed as environment
  variables, where `docker inspect` prints them to anyone with Docker access.
- no resource limits anywhere, so one runaway container could take the host and
  the database on it down; and container logs that grew without bound.

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


def _secret_targets(service: dict) -> set[str]:
    """File names a service sees under /run/secrets."""
    return {
        entry.get("target", entry["source"]) if isinstance(entry, dict) else entry
        for entry in service.get("secrets", [])
    }


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


class TestMigrationsRunOnce:
    """Migrations are a one-shot job the API waits for, not something it does."""

    @pytest.fixture(scope="class")
    def migrate(self, compose) -> dict:
        assert "migrate" in compose["services"], "there must be a dedicated migrate job"
        return compose["services"]["migrate"]

    def test_the_job_migrates_and_is_never_restarted(self, migrate):
        assert migrate["command"] == ["migrate"]
        # `restart: unless-stopped` would re-run a *failed* migration in a loop,
        # and re-run a successful one on every daemon restart.
        assert str(migrate.get("restart")) == "no"
        assert "ports" not in migrate and "healthcheck" not in migrate

    def test_it_is_the_same_image_as_the_api(self, migrate, backend):
        """The code that migrates the schema must be the code that then reads it."""
        assert migrate["image"] == backend["image"]
        assert migrate["build"] == backend["build"]

    def test_the_api_waits_for_it_to_succeed(self, backend):
        condition = backend["depends_on"]["migrate"]["condition"]
        assert condition == "service_completed_successfully", (
            "service_started would let the API come up beside a failing migration"
        )

    def test_it_waits_for_a_database_that_is_ready(self, migrate):
        assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"

    def test_it_validates_the_same_settings_the_api_does(self, migrate, backend):
        """alembic imports the application's settings; a missing secret must fail here too."""
        assert migrate["environment"]["DATABASE_URL"] == backend["environment"]["DATABASE_URL"]
        assert _secret_targets(backend) <= _secret_targets(migrate)

    def test_only_the_job_that_provisions_the_admin_can_read_its_password(self, migrate, backend):
        assert "admin_password" in _secret_targets(migrate)
        assert "admin_password" not in _secret_targets(backend)
        # Blank rather than absent, in both: .env is passed through whole by
        # env_file, and only an explicit empty value under `environment:`
        # overrides it. The migrate container is kept after it exits, so a
        # value here would sit in `docker inspect` indefinitely.
        assert backend["environment"].get("ADMIN_PASSWORD") == ""
        assert migrate["environment"].get("ADMIN_PASSWORD") == ""

    def test_the_entrypoint_does_not_migrate_when_serving_by_default(self):
        source = ENTRYPOINT.read_text()
        assert '"${RUN_MIGRATIONS_ON_START:-false}" = "true"' in source


class TestSecretsAreFilesNotVariables:
    SECRET_VARIABLES = ("SECRET_KEY", "DRONE_API_KEY", "DATABASE_PASSWORD", "POSTGRES_PASSWORD")

    @pytest.mark.parametrize("service", ["backend", "migrate"])
    def test_every_secret_variable_is_explicitly_blank(self, compose, service):
        """Blank, not absent.

        env_file passes .env through whole, and .env may still hold these from
        before they were files. Only a value under `environment:` overrides
        env_file, and the application reads an empty value as unset -- so the
        blank is what guarantees the secret reaches the container only as a file.
        """
        env = compose["services"][service]["environment"]
        for key in self.SECRET_VARIABLES:
            assert env.get(key) == "", f"{service}.{key} = {env.get(key)!r}"

    def test_no_service_interpolates_a_secret_from_the_shell(self):
        source = COMPOSE.read_text()
        for key in ("SECRET_KEY", "DRONE_API_KEY", "POSTGRES_PASSWORD", "ADMIN_PASSWORD"):
            assert "${" + key not in source, f"${{{key}}} is interpolated into the compose file"

    def test_the_database_url_carries_no_password(self, backend):
        url = backend["environment"]["DATABASE_URL"]
        credentials = url.split("://", 1)[1].split("@", 1)[0]
        assert ":" not in credentials, url

    def test_the_api_mounts_the_names_the_application_looks_for(self, backend):
        """config.py matches a secret to a setting by file name."""
        assert _secret_targets(backend) == {
            "secret_key",
            "secret_key_previous",
            "drone_api_key",
            "database_password",
        }

    def test_postgres_reads_its_password_from_the_file(self, compose):
        postgres = compose["services"]["postgres"]
        env = postgres["environment"]
        assert env["POSTGRES_PASSWORD_FILE"] == "/run/secrets/postgres_password"
        # The image refuses to start when both are set.
        assert "POSTGRES_PASSWORD" not in env
        assert "postgres_password" in _secret_targets(postgres)

    def test_every_mounted_secret_is_declared_and_lives_in_the_ignored_directory(self, compose):
        declared = compose["secrets"]
        used = {
            entry["source"] if isinstance(entry, dict) else entry
            for svc in compose["services"].values()
            for entry in svc.get("secrets", [])
        }
        assert used <= set(declared), used - set(declared)
        for name, spec in declared.items():
            assert _default(spec["file"].rsplit("/", 1)[0]) == "./secrets", (name, spec)
        assert "/secrets/" in (ROOT / ".gitignore").read_text().splitlines()


def _bytes(value: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    text = _default(value).lower().rstrip("b")
    return int(float(text[:-1]) * units[text[-1]]) if text[-1] in units else int(text)


class TestEveryContainerIsContained:
    """A limit on every service, sized from measurement, plus log rotation."""

    @pytest.fixture(scope="class")
    def services(self, compose) -> dict:
        return compose["services"]

    def test_every_service_has_memory_cpu_and_pid_limits(self, services):
        for name, svc in services.items():
            limits = svc.get("deploy", {}).get("resources", {}).get("limits", {})
            for key in ("memory", "cpus", "pids"):
                assert key in limits, f"{name} has no {key} limit"
            assert _bytes(limits["memory"]) >= 64 * 1024**2, f"{name}: implausibly small"

    def test_every_service_rotates_its_logs(self, services):
        for name, svc in services.items():
            options = svc.get("logging", {}).get("options", {})
            assert "max-size" in options and "max-file" in options, f"{name} logs without bound"

    def test_every_service_forbids_privilege_escalation(self, services):
        for name, svc in services.items():
            assert "no-new-privileges:true" in svc.get("security_opt", []), name

    @pytest.mark.parametrize("name", ["backend", "migrate", "frontend"])
    def test_unprivileged_services_drop_every_capability(self, services, name):
        assert services[name].get("cap_drop") == ["ALL"], name

    def test_the_backend_limit_clears_its_measured_footprint_with_room(self, backend):
        """270 MiB with the model and SHAP loaded; detections and the pool need headroom."""
        assert _bytes(backend["deploy"]["resources"]["limits"]["memory"]) >= 768 * 1024**2

    def test_postgres_memory_settings_fit_inside_its_limit(self, services):
        """timescaledb-tune sizes postgres to the HOST; the limit must win."""
        postgres = services["postgres"]
        limit = _bytes(postgres["deploy"]["resources"]["limits"]["memory"])
        command = " ".join(postgres["command"])
        shared = _bytes(re.search(r"shared_buffers=([^\s\"]+)", command).group(1))
        cache = _bytes(re.search(r"effective_cache_size=([^\s\"]+)", command).group(1))
        assert shared <= limit // 3, "shared_buffers must leave room for connections and work_mem"
        assert cache <= limit, "effective_cache_size beyond the limit misleads the planner"
        assert "shm_size" in postgres, "parallel queries need more than Docker's 64 MB /dev/shm"

    def test_redis_sheds_keys_before_it_can_be_oom_killed(self, services):
        redis = services["redis"]
        command = redis["command"]
        limit = _bytes(redis["deploy"]["resources"]["limits"]["memory"])
        maxmemory = _bytes(command[command.index("--maxmemory") + 1])
        assert maxmemory < limit
        assert command[command.index("--maxmemory-policy") + 1] == "volatile-lru"
        assert command[command.index("--appendonly") + 1] == "no", "nothing in redis needs persistence"

