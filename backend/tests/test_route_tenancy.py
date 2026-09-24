"""Every route is classified, and every classification is enforced.

This is the standing guarantee that tenant isolation is a property of the
application rather than of the care taken on the day each route was written.

Three layers, because no single one is sufficient:

  1. **Inventory.** Every route must appear in ROUTE_POLICY. A route that is
     added without being classified fails the suite, so the decision cannot be
     skipped by omission -- which is how tenancy holes actually appear.

  2. **Structure.** A route classified as touching tenant data must resolve a
     TenantContext. Without one it has no tenant to scope to.

  3. **Query.** That route's handler -- or a helper it calls -- must actually
     reference `organization_id`. Structure alone cannot catch the real failure
     mode: a route that authenticates correctly, resolves a tenant, and then
     queries the table without filtering on it.

Layer 3 is deliberately a source-level check. It is coarse, and it is the only
thing that generalises to every route without writing a bespoke fixture per
endpoint. Routes whose isolation genuinely cannot be proved this way carry an
explicit, justified exemption rather than being quietly dropped.

Behavioural proof for the highest-value routes lives in
test_tenant_isolation_live.py, which seeds two organizations and checks that one
cannot see the other's rows. The WebSocket, which has no scoped query to
inspect, is covered by test_websocket_tenancy.py.

This suite was written against a live defect and caught it: GET /system/health
counted every drone and every incident in the database, so an operator saw other
tenants' fleet size and incident totals on the dashboard, and their own health
percentage was reduced by incidents they could not see.
"""

import inspect
import os
import sys

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from middleware.auth_middleware import get_current_user, get_tenant_context

# --------------------------------------------------------------- categories

#: Reads or writes rows owned by an organization. Must resolve a tenant *and*
#: filter on organization_id.
TENANT_DATA = "tenant-data"

#: Requires a tenant context so a permission can be checked, but touches no
#: tenant-owned rows -- model metadata, detector configuration, inference over a
#: payload the caller supplied. Nothing to scope, so layer 3 does not apply.
AUTHZ_ONLY = "authz-only"

#: Acts only on the calling user's own record. Scoped by identity, not tenancy.
SELF = "self"

#: Deliberately unauthenticated. Every entry needs a reason it is safe to expose.
PUBLIC = "public"


ROUTE_POLICY: dict[tuple[str, str], str] = {
    # --- auth ---------------------------------------------------------------
    ("POST", "/auth/login"): PUBLIC,
    ("POST", "/auth/logout"): SELF,
    # Mints a socket ticket for the caller's own session, carrying that
    # session's organization and expiry. Nothing else is readable through it.
    ("POST", "/auth/ws-ticket"): SELF,

    # --- users --------------------------------------------------------------
    ("POST", "/users/"): TENANT_DATA,
    ("GET", "/users/"): TENANT_DATA,
    ("GET", "/users/me"): SELF,
    ("PATCH", "/users/me"): SELF,
    # Administering somebody else's account: both scope the lookup to the
    # caller's organization, and a user elsewhere reads as absent.
    ("PATCH", "/users/{user_id}"): TENANT_DATA,
    ("DELETE", "/users/{user_id}"): TENANT_DATA,
    ("POST", "/users/me/password"): SELF,

    # --- telemetry ----------------------------------------------------------
    ("POST", "/telemetry/ingest"): TENANT_DATA,
    ("GET", "/telemetry/latest"): TENANT_DATA,
    ("GET", "/telemetry/history"): TENANT_DATA,
    ("GET", "/telemetry/{drone_id}"): TENANT_DATA,
    ("GET", "/telemetry/{drone_id}/latest"): TENANT_DATA,
    ("GET", "/telemetry/health/status"): PUBLIC,

    # --- incidents ----------------------------------------------------------
    ("GET", "/incidents/"): TENANT_DATA,
    ("GET", "/incidents/open"): TENANT_DATA,
    ("GET", "/incidents/stats"): TENANT_DATA,
    ("GET", "/incidents/{id}"): TENANT_DATA,
    ("POST", "/incidents/{id}/acknowledge"): TENANT_DATA,
    ("POST", "/incidents/{id}/investigate"): TENANT_DATA,
    ("POST", "/incidents/{id}/contain"): TENANT_DATA,
    ("POST", "/incidents/{id}/resolve"): TENANT_DATA,
    ("POST", "/incidents/{id}/close"): TENANT_DATA,
    ("POST", "/incidents/{id}/assign"): TENANT_DATA,
    ("GET", "/incidents/audit/logs"): TENANT_DATA,

    # --- drones and commands ------------------------------------------------
    ("GET", "/drones"): TENANT_DATA,
    ("POST", "/drones/{drone_id}/command"): TENANT_DATA,
    ("POST", "/drones/{drone_id}/command/{command_id}/approve"): TENANT_DATA,
    ("GET", "/drones/{drone_id}/commands"): TENANT_DATA,
    ("POST", "/drones/{drone_id}/credentials"): TENANT_DATA,
    ("GET", "/drones/{drone_id}/credentials"): TENANT_DATA,
    ("DELETE", "/drones/{drone_id}/credentials/{credential_id}"): TENANT_DATA,

    # --- geofence -----------------------------------------------------------
    ("GET", "/geofence/zones"): TENANT_DATA,
    ("POST", "/geofence/zones"): TENANT_DATA,
    ("DELETE", "/geofence/zones/{zone_id}"): TENANT_DATA,

    # --- settings -----------------------------------------------------------
    ("GET", "/settings/"): TENANT_DATA,
    ("PATCH", "/settings/"): TENANT_DATA,

    # --- AI -----------------------------------------------------------------
    # Behind ai.explain, but none of these read tenant-owned rows: they report
    # on the model artifact and the detector configuration, or score a payload
    # the caller supplied in the request body.
    ("POST", "/ai/predict"): AUTHZ_ONLY,
    ("GET", "/ai/model/status"): AUTHZ_ONLY,
    ("GET", "/ai/model/info"): AUTHZ_ONLY,
    ("GET", "/ai/detection/status"): AUTHZ_ONLY,
    ("POST", "/ai/explain"): AUTHZ_ONLY,
    ("GET", "/ai/explanation/model"): AUTHZ_ONLY,

    # --- system -------------------------------------------------------------
    ("GET", "/"): PUBLIC,
    ("GET", "/health"): PUBLIC,
    # Readiness for the container health check and orchestrators: probes
    # postgres and Redis, returns 503 when one is down. Reports dependency
    # state and nothing tenant-owned.
    ("GET", "/ready"): PUBLIC,
    # Prometheus exposition. Counters and gauges, no tenant rows. nginx
    # answers 404 for it and the API port is loopback-only; METRICS_TOKEN adds
    # a bearer check on top for anything else.
    ("GET", "/metrics"): PUBLIC,
    ("GET", "/system/health"): TENANT_DATA,

    # --- websocket ----------------------------------------------------------
    # Authenticated inside the handler from a query-string token, because the
    # WebSocket handshake carries no Authorization header. It resolves the
    # user's organization and subscribes only to that organization's channel.
    ("WS", "/ws/telemetry"): TENANT_DATA,
}

#: Routes that cannot satisfy the layer-3 source check, each with the reason and
#: the test that covers it instead. Deliberately tiny: an entry here is a promise
#: that isolation is proved somewhere else.
LAYER3_EXEMPT: dict[tuple[str, str], str] = {
    ("WS", "/ws/telemetry"): (
        "Scoping happens in ws_manager, not in a query: the handler resolves the "
        "user's organization and subscribes to that organization's channel only. "
        "Covered behaviourally by tests/test_websocket_tenancy.py."
    ),
}


# ------------------------------------------------------------------ helpers

def walk_routes(routes):
    """Every route, descending into included routers.

    FastAPI 0.141 keeps included routers as `_IncludedRouter` wrappers instead of
    flattening them into `app.routes`. Iterating `app.routes` directly therefore
    yields only the three handlers declared on `app` itself -- so a test written
    the obvious way would pass while checking almost nothing.
    """
    for route in routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            yield route
        else:
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk_routes(nested.routes)


def route_key(route) -> tuple[str, str]:
    if isinstance(route, APIWebSocketRoute):
        return ("WS", route.path)
    methods = sorted(route.methods - {"HEAD", "OPTIONS"})
    return (methods[0], route.path)


def dependency_callables(dependant, seen=None):
    if seen is None:
        seen = set()
    out = []
    for sub in dependant.dependencies:
        if sub.call is not None and id(sub.call) not in seen:
            seen.add(id(sub.call))
            out.append(sub.call)
        out.extend(dependency_callables(sub, seen))
    return out


def resolves_tenant(route) -> bool:
    if isinstance(route, APIWebSocketRoute):
        return False
    deps = dependency_callables(route.dependant)
    # require_permission() returns a closure named "checker" that depends on
    # get_tenant_context; match either form.
    return get_tenant_context in deps or any(
        getattr(d, "__name__", "") == "checker" for d in deps
    )


def resolves_user(route) -> bool:
    if isinstance(route, APIWebSocketRoute):
        return False
    return get_current_user in dependency_callables(route.dependant)


def effective_source(endpoint) -> str:
    """The handler's source plus that of same-module helpers it calls.

    Handlers routinely delegate the scoped query -- `_load_incident`,
    `get_or_create_settings` -- so checking the handler body alone would report
    a false failure for correctly-scoped routes.
    """
    try:
        source = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return ""

    module = sys.modules.get(endpoint.__module__)
    if module is None:
        return source

    for name, member in vars(module).items():
        if not inspect.isfunction(member) or member is endpoint:
            continue
        if name in source:
            try:
                source += "\n" + inspect.getsource(member)
            except (OSError, TypeError):
                pass
    return source


ALL_ROUTES = sorted(walk_routes(app.routes), key=route_key)
ROUTE_IDS = [f"{m} {p}" for m, p in map(route_key, ALL_ROUTES)]
TENANT_DATA_ROUTES = [r for r in ALL_ROUTES if ROUTE_POLICY.get(route_key(r)) == TENANT_DATA]


# ------------------------------------------------------- layer 1: inventory

def test_the_application_actually_exposes_routes():
    """Guards the guard.

    If `walk_routes` stopped descending into included routers -- a FastAPI
    upgrade could do that -- every parametrised test below would receive an
    empty list and pass vacuously. This is the tripwire for that.
    """
    assert len(ALL_ROUTES) > 30, (
        f"Only {len(ALL_ROUTES)} routes discovered. Route walking is probably "
        "broken, which would make the rest of this file pass while checking nothing."
    )


@pytest.mark.parametrize("route", ALL_ROUTES, ids=ROUTE_IDS)
def test_every_route_is_classified(route):
    """A new route must be classified before it can ship."""
    key = route_key(route)
    assert key in ROUTE_POLICY, (
        f"{key[0]} {key[1]} ({route.endpoint.__module__}.{route.endpoint.__name__}) "
        "is not in ROUTE_POLICY. Classify it as TENANT_DATA, AUTHZ_ONLY, SELF or "
        "PUBLIC. If it reads rows owned by an organization, it is TENANT_DATA."
    )


def test_policy_has_no_entries_for_routes_that_no_longer_exist():
    """Keeps the policy honest as routes are removed."""
    live = {route_key(r) for r in ALL_ROUTES}
    stale = set(ROUTE_POLICY) - live
    assert not stale, f"ROUTE_POLICY references routes that no longer exist: {sorted(stale)}"


def test_public_routes_are_few_and_deliberate():
    """A growing public surface should require an explicit decision here."""
    public = {k for k, v in ROUTE_POLICY.items() if v == PUBLIC}
    assert public == {
        ("GET", "/"),
        ("GET", "/health"),
        ("GET", "/ready"),
        ("GET", "/metrics"),
        ("POST", "/auth/login"),
        ("GET", "/telemetry/health/status"),
    }, (
        "The set of unauthenticated routes changed. Every entry must be safe to "
        "expose to the internet with no credentials at all."
    )


# ------------------------------------------------------- layer 2: structure

@pytest.mark.parametrize(
    "route",
    TENANT_DATA_ROUTES,
    ids=[f"{m} {p}" for m, p in map(route_key, TENANT_DATA_ROUTES)],
)
def test_tenant_data_routes_resolve_a_tenant(route):
    key = route_key(route)
    if isinstance(route, APIWebSocketRoute):
        pytest.skip("WebSocket authenticates inside the handler; see LAYER3_EXEMPT")
    assert resolves_tenant(route), (
        f"{key[0]} {key[1]} touches tenant-owned data but never resolves a "
        "TenantContext, so it has no organization to scope to. Add "
        "Depends(require_permission(...)) or Depends(get_tenant_context)."
    )


@pytest.mark.parametrize("route", ALL_ROUTES, ids=ROUTE_IDS)
def test_self_scoped_routes_authenticate(route):
    if ROUTE_POLICY.get(route_key(route)) != SELF:
        pytest.skip("not a self-scoped route")
    assert resolves_user(route) or resolves_tenant(route), (
        f"{route_key(route)} acts on the caller's own record but does not "
        "authenticate the caller."
    )


@pytest.mark.parametrize("route", ALL_ROUTES, ids=ROUTE_IDS)
def test_public_routes_really_are_the_declared_ones(route):
    """Nothing may become unauthenticated by accident."""
    key = route_key(route)
    if isinstance(route, APIWebSocketRoute):
        pytest.skip("WebSocket authenticates inside the handler")
    unauthenticated = not resolves_tenant(route) and not resolves_user(route)
    if unauthenticated:
        assert ROUTE_POLICY.get(key) == PUBLIC, (
            f"{key[0]} {key[1]} has no authentication dependency but is "
            f"classified {ROUTE_POLICY.get(key)!r}. Either add authentication or "
            "reclassify it as PUBLIC and justify the exposure."
        )


# ----------------------------------------------------------- layer 3: query

@pytest.mark.parametrize(
    "route",
    TENANT_DATA_ROUTES,
    ids=[f"{m} {p}" for m, p in map(route_key, TENANT_DATA_ROUTES)],
)
def test_tenant_data_routes_filter_on_organization(route):
    """The failure mode structure cannot catch.

    A route can authenticate correctly, resolve a tenant, and then query the
    table without filtering on it. That is exactly what GET /system/health did:
    it counted every drone and every incident in the database and returned the
    totals to whoever asked.
    """
    key = route_key(route)
    if key in LAYER3_EXEMPT:
        pytest.skip(LAYER3_EXEMPT[key])

    source = effective_source(route.endpoint)
    assert "organization_id" in source, (
        f"{key[0]} {key[1]} ({route.endpoint.__name__}) reads or writes "
        "tenant-owned rows but its implementation never mentions "
        "organization_id, so the query is not scoped to the caller's "
        "organization. Filter on it, or -- if isolation is genuinely enforced "
        "elsewhere -- add a justified entry to LAYER3_EXEMPT."
    )


def test_layer3_exemptions_stay_minimal():
    """An exemption is a promise that isolation is proved elsewhere."""
    assert len(LAYER3_EXEMPT) <= 2, (
        "Layer-3 exemptions are growing. Each one is a route whose tenant "
        "isolation this suite cannot verify; they should be rare and separately "
        "covered by a behavioural test."
    )


# ------------------------------------------------- does the guard guard?
#
# A test that enforces a property is only worth having if it fails when the
# property is broken. These check the checkers against handlers written to be
# wrong, so the suite cannot quietly degrade into passing on everything.
#
# The alternative -- editing a real router to confirm the failure -- proves it
# once, by hand, and leaves nothing behind.

def _unscoped_handler(db, tenant):
    """A handler that resolves a tenant and then ignores it."""
    return db.query(object).all()


def _scoped_handler(db, tenant):
    """The same handler written correctly."""
    return db.query(object).filter(object.organization_id == tenant.organization_id).all()


def _delegating_handler(db, tenant):
    """Correct, but via a helper -- the shape most incident routes use."""
    return _scoped_helper(db, tenant)


def _scoped_helper(db, tenant):
    return db.query(object).filter(object.organization_id == tenant.organization_id).first()


class TestTheCheckersDetectViolations:
    def test_layer3_rejects_a_handler_that_ignores_its_tenant(self):
        assert "organization_id" not in effective_source(_unscoped_handler), (
            "The layer-3 check would pass a handler that resolves a tenant and "
            "never filters on it -- exactly the GET /system/health defect."
        )

    def test_layer3_accepts_a_directly_scoped_handler(self):
        assert "organization_id" in effective_source(_scoped_handler)

    def test_layer3_follows_a_helper_one_level_down(self):
        """Without this, correctly-scoped delegating routes would fail falsely."""
        assert "organization_id" not in inspect.getsource(_delegating_handler)
        assert "organization_id" in effective_source(_delegating_handler)

    def test_route_walking_reaches_routers_not_just_the_app(self):
        """The failure that would make every other assertion vacuous."""
        paths = {route_key(r)[1] for r in ALL_ROUTES}
        assert "/incidents/" in paths and "/telemetry/ingest" in paths, (
            "Routes registered through include_router are not being discovered, "
            "so the parametrised tests above are running against almost nothing."
        )

    def test_every_classification_is_exercised_by_at_least_one_route(self):
        """A category nothing uses is a category nobody maintains."""
        live = {ROUTE_POLICY[route_key(r)] for r in ALL_ROUTES if route_key(r) in ROUTE_POLICY}
        assert live == {TENANT_DATA, AUTHZ_ONLY, SELF, PUBLIC}
