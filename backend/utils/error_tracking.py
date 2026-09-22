"""Error tracking: unhandled exceptions grouped and counted somewhere a person looks.

main.py's catch-all turns every unhandled exception into an opaque 500 and one
log line. Two hundred of the same traceback in a log file are two hundred
lines; in an error tracker they are one issue with a count, a first-seen, a
last-seen and the request that triggered it. That is the difference between
"the API is throwing 500s" and "PATCH /users/me fails when the email is unset,
since Tuesday, 214 times".

Off unless SENTRY_DSN is set. With it unset nothing here is imported at
request time and nothing changes.

What is sent is scrubbed here, before it leaves the process, whatever the
SDK's own defaults are: no Authorization or Cookie headers, no `token` query
parameter (the WebSocket handshake carries the JWT there), no password or key
fields in a request body, and no default PII. A stack trace can still carry a
local variable; that is what the tracker's own server-side scrubbing rules are
for, and the guide says to turn them on.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-drone-api-key", "proxy-authorization"}
SENSITIVE_FIELDS = {
    "password", "current_password", "new_password", "secret", "secret_key", "token",
    "access_token", "refresh_token", "api_key", "drone_api_key", "x-drone-api-key",
}
_TOKEN_IN_QUERY = re.compile(r"([?&](?:token|access_token|api_key)=)[^&\s]+", re.IGNORECASE)
REDACTED = "[redacted]"


def _scrub_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if str(key).lower() in SENSITIVE_FIELDS:
            cleaned[key] = REDACTED
        elif isinstance(value, Mapping):
            cleaned[key] = _scrub_mapping(value)
        elif isinstance(value, list):
            cleaned[key] = [_scrub_mapping(v) if isinstance(v, Mapping) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


def scrub_event(event: dict[str, Any], hint: Any = None) -> dict[str, Any]:
    """Sentry `before_send`: remove credentials from what would be reported."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, Mapping):
            request["headers"] = {
                k: (REDACTED if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()
            }
        for key in ("query_string", "url"):
            value = request.get(key)
            if isinstance(value, str):
                request[key] = _TOKEN_IN_QUERY.sub(r"\1" + REDACTED, "?" + value)[1:] if key == "query_string" else _TOKEN_IN_QUERY.sub(r"\1" + REDACTED, value)
        if isinstance(request.get("data"), Mapping):
            request["data"] = _scrub_mapping(request["data"])
        if isinstance(request.get("cookies"), Mapping):
            request["cookies"] = {k: REDACTED for k in request["cookies"]}
    extra = event.get("extra")
    if isinstance(extra, Mapping):
        event["extra"] = _scrub_mapping(extra)
    return event


def init_error_tracking(dsn: str | None, *, environment: str, release: str | None, logger) -> bool:
    """Start the SDK if a DSN is configured. Returns whether it was."""
    if not dsn:
        logger.info("Error tracking disabled (SENTRY_DSN not set).")
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        send_default_pii=False,
        before_send=scrub_event,
        # Errors are the point. A small trace sample gives latency context
        # for them without shipping every request.
        traces_sample_rate=0.05,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    logger.info(f"Error tracking enabled (environment={environment}, release={release or 'unset'}).")
    return True
