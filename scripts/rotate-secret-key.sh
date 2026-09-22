#!/bin/sh
# Rotate SECRET_KEY, the key every login token is signed with.
#
#   scripts/rotate-secret-key.sh              start a rotation
#   scripts/rotate-secret-key.sh --finish     end it, once old tokens have expired
#   scripts/rotate-secret-key.sh --emergency  the key leaked: log everyone out now
#
# A rotation has two halves, because tokens already issued were signed with the
# old key and live for ACCESS_TOKEN_EXPIRE_MINUTES (60 by default):
#
#   start    secret_key -> secret_key_previous, a fresh secret_key is generated.
#            New tokens are signed with the new key; old ones still verify
#            against the previous one. Nobody is logged out.
#   finish   secret_key_previous is emptied. Run it after the token lifetime has
#            passed. From then on the old key verifies nothing.
#
# --emergency skips the grace period on purpose: if the key has leaked, anyone
# holding it can mint a valid admin token, and the only fix is for the old key
# to stop verifying immediately. Every user has to sign in again.
#
# After any of them, restart the API so it reads the new files:
#   docker compose up -d --force-recreate backend
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${SWARMGUARD_SECRETS_DIR:-$ROOT/secrets}"
MODE="${1:-start}"

[ -s "$DIR/secret_key" ] || { echo "No $DIR/secret_key. Run scripts/init-secrets.sh first." >&2; exit 1; }

# The files are read-only and the directory is not: replace, never write into.
put() {
  rm -f "$DIR/$1"
  ( umask 077; printf '%s' "$2" > "$DIR/$1" )
  chmod 444 "$DIR/$1"
}

RESTART="Restart the API to apply:  docker compose up -d --force-recreate backend"

case "$MODE" in
  start)
    if [ -s "$DIR/secret_key_previous" ]; then
      echo "A rotation is already in progress (secret_key_previous is not empty)." >&2
      echo "Starting another would drop a key that live tokens may still be signed with." >&2
      echo "Run --finish first, after the token lifetime has passed." >&2
      exit 1
    fi
    put secret_key_previous "$(cat "$DIR/secret_key")"
    put secret_key "$(openssl rand -hex 32)"
    echo "Rotation started: new tokens use the new key, existing sessions stay valid."
    echo "$RESTART"
    echo "Then, after ACCESS_TOKEN_EXPIRE_MINUTES (default 60):  $0 --finish"
    ;;
  --finish)
    put secret_key_previous ""
    echo "Rotation finished: the previous key no longer verifies anything."
    echo "$RESTART"
    ;;
  --emergency)
    put secret_key_previous ""
    put secret_key "$(openssl rand -hex 32)"
    echo "Emergency rotation: every existing session is invalid as of the restart."
    echo "$RESTART"
    ;;
  *)
    echo "usage: $0 [--finish | --emergency]" >&2
    exit 2
    ;;
esac
