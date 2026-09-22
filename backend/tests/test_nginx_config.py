"""frontend/nginx.conf is the only thing between the network and the API, so its
security-relevant shape is pinned.

Two regressions are guarded in particular:

* Anything *served* on port 80. Passwords, JWTs, the device key and telemetry
  all crossed the wire in clear text until TLS was added; one stray `proxy_pass`
  in the port-80 server would put them back there, and the site would still
  look fine because browsers follow the redirect for the page itself.

* The add_header inheritance trap. nginx inherits add_header from the enclosing
  level only if the current level declares none, so a single `add_header` in a
  location silently discards every security header. The static-asset location
  did exactly that: every .js and .css was served with no CSP and no nosniff.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
NGINX = ROOT / "frontend" / "nginx.conf"
SNIPPET = ROOT / "frontend" / "nginx" / "security-headers.conf"
DOCKERFILE = ROOT / "frontend" / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
INCLUDE = "include /etc/nginx/snippets/security-headers.conf;"


def _without_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    """(header, body) for every `<keyword> ... { body }`, brace-matched."""
    found = []
    for match in re.finditer(rf"(?m)^\s*({keyword}\b[^{{;]*)\{{", text):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        found.append((match.group(1).strip(), text[match.end(): i - 1]))
    return found


@pytest.fixture(scope="module")
def servers() -> dict[str, str]:
    source = _without_comments(NGINX.read_text())
    by_port = {}
    for _, body in _blocks(source, "server"):
        port = "443" if re.search(r"listen\s+443", body) else "80"
        by_port[port] = body
    assert set(by_port) == {"80", "443"}, "expected one plain and one TLS server"
    return by_port


class TestPort80ServesNothing:
    def test_it_does_not_proxy_and_has_no_document_root_for_the_app(self, servers):
        plain = servers["80"]
        assert "proxy_pass" not in plain, "the API must never be reachable over plain HTTP"
        assert "/usr/share/nginx/html" not in plain, "the application must not be served in clear"

    def test_everything_else_is_redirected_to_https(self, servers):
        locations = dict(_blocks(servers["80"], "location"))
        assert "return 301 https://$host$request_uri;" in locations["location /"]

    def test_only_the_probe_and_the_acme_challenge_are_answered(self, servers):
        locations = {header for header, _ in _blocks(servers["80"], "location")}
        assert locations == {
            "location = /healthz",
            "location ^~ /.well-known/acme-challenge/",
            "location /",
        }


class TestTheTlsServer:
    def test_it_listens_with_tls_on_ipv4_and_ipv6(self, servers):
        tls = servers["443"]
        assert re.search(r"listen\s+443\s+ssl;", tls)
        assert re.search(r"listen\s+\[::\]:443\s+ssl;", tls)

    def test_deprecated_protocol_versions_are_off(self, servers):
        protocols = re.search(r"ssl_protocols\s+([^;]+);", servers["443"]).group(1).split()
        assert set(protocols) == {"TLSv1.2", "TLSv1.3"}, protocols

    def test_every_tls12_suite_has_forward_secrecy_and_aead(self, servers):
        suites = re.search(r"ssl_ciphers\s+([^;]+);", servers["443"]).group(1).split(":")
        for suite in suites:
            assert suite.startswith("ECDHE-"), f"{suite}: no forward secrecy"
            assert "GCM" in suite or "CHACHA20-POLY1305" in suite, f"{suite}: not AEAD"

    def test_session_tickets_are_off(self, servers):
        assert re.search(r"ssl_session_tickets\s+off;", servers["443"])

    def test_the_certificate_is_not_part_of_the_image(self):
        """A certificate in an image is a certificate in every registry it reaches."""
        dockerfile = DOCKERFILE.read_text()
        for line in dockerfile.splitlines():
            if line.strip().startswith(("COPY", "ADD")):
                assert not re.search(r"\.(crt|key|pem)\b", line), line

    @pytest.mark.parametrize("location", ["location /api/", "location /ws/"])
    def test_the_backend_is_told_the_original_scheme(self, servers, location):
        body = dict(_blocks(servers["443"], "location"))[location]
        assert "proxy_set_header X-Forwarded-Proto $scheme;" in body


class TestFingerprint:
    """Found by the live exercise: 'server: nginx/1.31.6' on every response."""

    def test_the_version_is_not_advertised(self, servers):
        for port, body in servers.items():
            assert re.search(r"server_tokens\s+off;", body), f"port {port} advertises the nginx version"

    def test_the_schema_and_docs_are_not_reachable_through_the_proxy(self, servers):
        locations = dict(_blocks(servers["443"], "location"))
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            body = locations.get(f"location = {path}")
            assert body and "return 404;" in body, f"{path} is exposed through the public proxy"


class TestSecurityHeaders:
    REQUIRED = (
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Content-Security-Policy",
    )

    def test_the_snippet_sets_each_one_on_every_response_code(self):
        snippet = _without_comments(SNIPPET.read_text())
        for header in self.REQUIRED:
            line = next((ln for ln in snippet.splitlines() if f"add_header {header} " in ln), None)
            assert line, f"{header} is missing"
            assert line.rstrip().endswith("always;"), f"{header} is not sent on error responses"

    def test_hsts_lasts_at_least_six_months(self):
        max_age = int(re.search(r"max-age=(\d+)", SNIPPET.read_text()).group(1))
        assert max_age >= 15_552_000

    def test_the_tls_server_includes_them(self, servers):
        top_level = re.sub(r"location[^{]*\{[^{}]*\}", "", servers["443"])
        assert INCLUDE in top_level

    def test_no_location_drops_them_by_setting_a_header_of_its_own(self, servers):
        """The inheritance trap: one add_header discards every inherited one."""
        for header, body in _blocks(servers["443"], "location"):
            if "add_header" in body:
                assert INCLUDE in body, (
                    f"`{header}` sets a header without re-including the security headers, "
                    "so nginx serves it with none of them"
                )

    def test_there_is_one_cache_control_per_asset(self, servers):
        assets = next(b for h, b in _blocks(servers["443"], "location") if "css|js" in h)
        assert assets.count("Cache-Control") == 1
        assert "expires" not in assets, "`expires` emits a second Cache-Control header"

    def test_the_image_ships_the_snippet_where_the_config_looks_for_it(self):
        assert "/etc/nginx/snippets/security-headers.conf" in DOCKERFILE.read_text()


class TestTheWebSocketTokenStaysOutOfTheLog:
    def test_the_ws_location_is_not_logged(self, servers):
        body = dict(_blocks(servers["443"], "location"))["location /ws/"]
        assert "access_log off;" in body


class TestCompose:
    @pytest.fixture(scope="class")
    def frontend(self) -> dict:
        with COMPOSE.open() as fh:
            return yaml.safe_load(fh)["services"]["frontend"]

    def test_https_is_published(self, frontend):
        assert {"80:80", "443:443"} <= {str(p) for p in frontend["ports"]}

    def test_certificates_are_mounted_read_only(self, frontend):
        mount = next(v for v in frontend["volumes"] if ":/etc/nginx/certs" in v)
        assert mount.endswith(":ro"), mount

    def test_the_health_probe_does_not_depend_on_the_redirect(self, frontend):
        assert frontend["healthcheck"]["test"][-1] == "http://127.0.0.1/healthz"
        assert "/healthz" in DOCKERFILE.read_text()
