#!/bin/sh
# Container entrypoint. One image, two jobs:
#
#   migrate   apply migrations, optionally provision the first admin, exit.
#   serve     start the API (default). Does NOT migrate.
#
# This used to run `alembic upgrade head` and then serve, on every start. With
# one replica that is fine. Start two together and both run the same DDL against
# the same database at the same moment. So migrating is now its own one-shot job
# -- the `migrate` service in docker-compose.yml, an init container or a Job
# elsewhere -- and the API refuses to serve a schema that is behind
# (utils/schema_check.py) instead of quietly fixing it up.
set -eu

run_migrations() {
  echo "[entrypoint] Applying database migrations..."
  # alembic/env.py holds a PostgreSQL advisory lock for the length of the run,
  # so two of these overlapping queue up rather than race.
  alembic upgrade head

  # Provisioning is opt-in: set both variables to create the default
  # organization and its admin. Idempotent, so it is safe to leave configured.
  # It lives with the migrations because it needs the schema and, like them,
  # must happen once rather than once per replica.
  #
  # The password is read from its mounted secret when the variable is empty.
  # Exporting it here puts it in this shell and bootstrap.py only; passed as a
  # container variable it would sit in `docker inspect swarmguard-migrate` for
  # as long as the exited container is kept.
  ADMIN_PASSWORD_FILE="${SECRETS_DIR:-/run/secrets}/admin_password"
  if [ -z "${ADMIN_PASSWORD:-}" ] && [ -s "$ADMIN_PASSWORD_FILE" ]; then
    ADMIN_PASSWORD="$(cat "$ADMIN_PASSWORD_FILE")"
    export ADMIN_PASSWORD
  fi
  if [ -n "${ADMIN_USERNAME:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    echo "[entrypoint] Provisioning admin '${ADMIN_USERNAME}'..."
    python bootstrap.py
  else
    echo "[entrypoint] ADMIN_USERNAME/ADMIN_PASSWORD not set; skipping provisioning."
  fi
}

MODE="${1:-serve}"

case "$MODE" in
  migrate)
    run_migrations
    echo "[entrypoint] Migrations complete."
    ;;

  serve)
    # For a single container run by hand (`docker run`), where there is no job
    # to do it first. Safe to leave on -- the lock above serialises it -- but
    # every replica then pays for a no-op alembic run at start, and a failed
    # migration takes the API down with it instead of failing on its own.
    if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
      run_migrations
    fi

    echo "[entrypoint] Starting API server..."
    # X-Forwarded-For is honoured only from FORWARDED_ALLOW_IPS, which compose
    # sets to the nginx container's static address. The fallback used to be
    # "*": the header was trusted from any peer, so a client could pick its own
    # address for the login rate limit and the audit trail. 127.0.0.1 is
    # uvicorn's own default -- run outside compose with nothing set, forwarded
    # headers are ignored and every client keys as the proxy. Fail closed,
    # never fail open.
    exec uvicorn main:app \
      --host 0.0.0.0 \
      --port 8000 \
      --proxy-headers \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
    ;;

  *)
    # Anything else is run as given: `docker compose run --rm backend alembic current`.
    exec "$@"
    ;;
esac
