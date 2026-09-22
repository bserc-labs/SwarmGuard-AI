#!/bin/sh
# A self-signed certificate for LOCAL DEVELOPMENT, written to ./certs.
#
#   scripts/make-dev-cert.sh [hostname]      default: localhost
#
# You do not need this to run the stack: with ./certs empty the frontend
# container generates a self-signed certificate at start. But it generates a
# *new* one every time the container is recreated, so the browser asks you to
# accept the warning again each time. A certificate in ./certs is stable: accept
# it once (or add it to your system trust store) and it stays accepted.
#
# NOT for a server. It proves nothing about who is on the other end. For a real
# deployment mount a certificate from Let's Encrypt or your own CA --
# docs/OPERATIONS.md.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${SWARMGUARD_CERTS_DIR:-$ROOT/certs}"
CN="${1:-localhost}"

if [ -s "$DIR/tls.crt" ] || [ -s "$DIR/tls.key" ]; then
  echo "$DIR already holds a certificate; not overwriting it." >&2
  echo "Remove tls.crt and tls.key first if you really want a new one." >&2
  exit 1
fi

SAN="DNS:localhost,IP:127.0.0.1,IP:::1"
[ "$CN" = "localhost" ] || SAN="DNS:$CN,$SAN"

mkdir -p "$DIR"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -keyout "$DIR/tls.key" -out "$DIR/tls.crt" \
  -subj "/CN=$CN" -addext "subjectAltName=$SAN" >/dev/null 2>&1

# nginx runs as an unprivileged user whose uid does not exist on the host, so
# the key has to be readable through the bind mount; the directory is what keeps
# other host users out. Same arrangement as ./secrets.
chmod 700 "$DIR"
chmod 444 "$DIR/tls.crt" "$DIR/tls.key"

echo "Wrote a self-signed certificate for '$CN' to $DIR (valid 365 days)."
echo "Apply it:  docker compose up -d --force-recreate frontend"
