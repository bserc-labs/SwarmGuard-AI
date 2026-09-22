#!/bin/sh
# Deploy a published image tag, smoke-test it, and roll back by itself if the
# smoke test fails.
#
#   scripts/deploy.sh sha-<commit>     deploy that tag (the release job prints it)
#   scripts/deploy.sh --rollback       go back to the previously deployed tag
#   scripts/deploy.sh --status         what is deployed, and what came before it
#
# Runs on the host next to docker-compose.yml. State is two files under
# .deploy/ (gitignored): `current` and `previous`. A tag is a commit SHA, so
# "what is running" is always one exact commit and a rollback is one command.
#
# What a deploy does, in order:
#   1. pull the three images for the tag (fails here if the tag does not exist,
#      before anything running is touched)
#   2. `up -d --no-build`: the migrate job runs against the new code, the API
#      starts only if it succeeded, nginx last
#   3. smoke test: /healthz on port 80, then /api/ready over HTTPS through
#      nginx, until SMOKE_TIMEOUT_S passes
#   4. on success: record the tag; on failure: redeploy the previous tag, smoke
#      test that, and exit non-zero either way -- a failed deploy is never
#      reported as anything else, even after a successful rollback
#
# Rolling an image back does not roll the schema back. That is safe only
# because migrations must stay compatible with the previous release for one
# release (docs/OPERATIONS.md, "The rule that makes rollbacks safe"). The API
# of the previous release starts against the newer schema, sees a revision it
# does not know, warns, and serves.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${SWARMGUARD_DEPLOY_STATE:-$ROOT/.deploy}"
SMOKE_URL="${SWARMGUARD_SMOKE_URL:-https://localhost/api/ready}"
PROBE_URL="${SWARMGUARD_PROBE_URL:-http://localhost/healthz}"
SMOKE_TIMEOUT_S="${SWARMGUARD_SMOKE_TIMEOUT_S:-120}"
# -k only for a self-signed development certificate. Leave unset on a server.
CURL_TLS="${SWARMGUARD_SMOKE_INSECURE:+-k}"
COMPOSE="${SWARMGUARD_COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.prod.yml}"

cd "$ROOT"
mkdir -p "$STATE"

current() { [ -f "$STATE/current" ] && cat "$STATE/current" || true; }
previous() { [ -f "$STATE/previous" ] && cat "$STATE/previous" || true; }

run_stack() {
  # $1 = tag. `--no-build` because the prod override removed every build
  # section; if one crept back in, building on the server is not what anyone
  # wants a deploy to do quietly.
  SWARMGUARD_TAG="$1" $COMPOSE pull --quiet
  SWARMGUARD_TAG="$1" $COMPOSE up -d --no-build --remove-orphans
}

smoke() {
  deadline=$(( $(date +%s) + SMOKE_TIMEOUT_S ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -fsS -o /dev/null "$PROBE_URL" 2>/dev/null \
       && curl -fsS $CURL_TLS -o /dev/null "$SMOKE_URL" 2>/dev/null; then
      echo "[deploy] smoke test passed: $PROBE_URL and $SMOKE_URL answer"
      return 0
    fi
    sleep 3
  done
  echo "[deploy] smoke test FAILED: no healthy answer within ${SMOKE_TIMEOUT_S}s" >&2
  for svc in migrate backend frontend; do
    echo "[deploy] --- $svc: $($COMPOSE ps --format '{{.Status}}' "$svc" 2>/dev/null | head -n 1)" >&2
    $COMPOSE logs --no-log-prefix --tail 15 "$svc" 2>/dev/null >&2 || true
  done
  return 1
}

case "${1:-}" in
  --status)
    echo "current:  $(current)"
    echo "previous: $(previous)"
    exit 0
    ;;
  --rollback)
    target="$(previous)"
    [ -n "$target" ] || { echo "[deploy] nothing to roll back to" >&2; exit 1; }
    echo "[deploy] rolling back $(current) -> $target"
    run_stack "$target"
    smoke || { echo "[deploy] the previous release does not pass the smoke test either" >&2; exit 1; }
    current > "$STATE/previous.tmp"; mv "$STATE/previous.tmp" "$STATE/previous"
    printf '%s' "$target" > "$STATE/current"
    echo "[deploy] rolled back to $target"
    exit 0
    ;;
  sha-*)
    tag="$1"
    ;;
  "")
    echo "usage: $0 sha-<commit> | --rollback | --status" >&2; exit 2 ;;
  *)
    echo "[deploy] refusing '$1': deploy an immutable sha-<commit> tag, not a moving one" >&2
    exit 2
    ;;
esac

was="$(current)"
if [ "$was" = "$tag" ]; then
  echo "[deploy] $tag is already deployed"
  exit 0
fi

echo "[deploy] $was -> $tag"
run_stack "$tag"
if smoke; then
  [ -n "$was" ] && printf '%s' "$was" > "$STATE/previous"
  printf '%s' "$tag" > "$STATE/current"
  echo "[deploy] deployed $tag"
  exit 0
fi

if [ -z "$was" ]; then
  echo "[deploy] FAILED and there is no previous release to roll back to" >&2
  exit 1
fi
echo "[deploy] rolling back to $was" >&2
run_stack "$was"
if smoke; then
  echo "[deploy] FAILED to deploy $tag; $was is back and healthy" >&2
else
  echo "[deploy] FAILED to deploy $tag, and $was does NOT pass the smoke test after rollback" >&2
fi
exit 1
