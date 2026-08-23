#!/bin/sh
# Container entrypoint: bring the schema up to date, optionally provision the
# first admin, then serve. Without the migration step the application starts
# against an empty database on a fresh volume.
set -eu

echo "[entrypoint] Applying database migrations..."
alembic upgrade head

# Provisioning is opt-in: set both variables to create the default organization
# and its admin. Idempotent, so it is safe to leave configured.
if [ -n "${ADMIN_USERNAME:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
  echo "[entrypoint] Provisioning admin '${ADMIN_USERNAME}'..."
  python bootstrap.py
else
  echo "[entrypoint] ADMIN_USERNAME/ADMIN_PASSWORD not set; skipping provisioning."
fi

echo "[entrypoint] Starting API server..."
exec uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
