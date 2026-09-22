#!/bin/sh
# Create the secret files docker-compose.yml mounts at /run/secrets.
#
#   scripts/init-secrets.sh            create whatever is missing
#   scripts/init-secrets.sh --check    exit 1 if anything is missing or weak; change nothing
#
# Secrets used to be environment variables, which `docker inspect` prints to
# anyone with Docker access. They are now one file each under ./secrets/
# (gitignored), mounted read-only into the containers that need them.
#
# Never overwrites an existing file. For a value it has to create, it first
# looks in .env -- so a stack that is already running keeps the database
# password its volume was initialised with, and keeps every issued login valid
# -- and only otherwise generates one.
#
# It does not edit .env. Compose passes the secrets to the containers as empty
# variables, so leftovers in .env cannot leak into a container; delete them
# from .env once you have checked the stack comes up.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${SWARMGUARD_SECRETS_DIR:-$ROOT/secrets}"
ENV_FILE="${SWARMGUARD_ENV_FILE:-$ROOT/.env}"
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

# The last assignment of KEY in .env, without sourcing the file: a value may
# legitimately contain characters the shell would interpret.
from_env_file() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

generate() { openssl rand -hex 32; }

problems=0
created=""

# ensure <file> <ENV_KEY> <required: yes|no>
ensure() {
  file="$DIR/$1"; key="$2"; required="$3"
  if [ -s "$file" ]; then
    return 0
  fi
  value="$(from_env_file "$key")"
  origin="from $key in .env"
  if [ -z "$value" ] && [ "$required" = "yes" ]; then
    value="$(generate)"
    origin="generated"
  fi
  if $CHECK_ONLY; then
    if [ "$required" = "yes" ]; then
      echo "MISSING  $1"
      problems=$((problems + 1))
    fi
    return 0
  fi
  # Replace rather than write into: an empty optional file left by an earlier
  # run is read-only, and may now have a value to take from .env.
  rm -f "$file"
  # printf, not echo: no trailing newline to become part of a password.
  ( umask 077; printf '%s' "$value" > "$file" )
  if [ -n "$value" ]; then
    created="$created\n  $1  ($origin)"
  fi
}

if ! $CHECK_ONLY; then
  mkdir -p "$DIR"
fi

ensure secret_key        SECRET_KEY        yes
ensure drone_api_key     DRONE_API_KEY     yes
ensure postgres_password POSTGRES_PASSWORD yes
# Optional: the first admin's password. An empty file means "do not provision".
ensure admin_password    ADMIN_PASSWORD    no

# The application refuses secrets shorter than this; say so here rather than
# in a container log three commands later.
for name in secret_key drone_api_key; do
  if [ -f "$DIR/$name" ] && [ "$(wc -c < "$DIR/$name" | tr -d ' ')" -lt 32 ]; then
    echo "TOO SHORT  $name is under 32 characters; the API will refuse to start."
    problems=$((problems + 1))
  fi
done

if $CHECK_ONLY; then
  [ "$problems" -eq 0 ] && echo "secrets: ok ($DIR)"
  exit "$([ "$problems" -eq 0 ] && echo 0 || echo 1)"
fi

# The directory is what keeps other users on the host out. The files themselves
# must stay world-readable: compose bind-mounts them, and the containers read
# them as unprivileged users whose uid does not exist on the host.
chmod 700 "$DIR"
chmod 444 "$DIR"/secret_key "$DIR"/drone_api_key "$DIR"/postgres_password "$DIR"/admin_password

if [ -n "$created" ]; then
  printf 'Created in %s:%b\n' "$DIR" "$created"
else
  echo "Nothing to create; every secret already exists in $DIR."
fi
[ "$problems" -eq 0 ] || exit 1
