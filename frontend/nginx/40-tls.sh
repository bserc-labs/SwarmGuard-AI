#!/bin/sh
# Runs from /docker-entrypoint.d before nginx starts. Makes sure
# /etc/nginx/tls/tls.crt and tls.key exist, which nginx.conf points at.
#
#   certificate mounted at /etc/nginx/certs  ->  link to it
#   nothing mounted                          ->  generate a self-signed one
#
# Links, not copies: no second copy of the private key is made, and after a
# renewal `nginx -s reload` picks the new files up without a restart.
#
# The fallback exists so that `docker compose up` on a laptop still serves
# HTTPS instead of refusing to start. A self-signed certificate encrypts the
# connection; it does not prove who is on the other end, and every browser will
# say so. It must never be what a real deployment runs on, hence the noise.
set -eu

MOUNTED="${TLS_CERT_DIR:-/etc/nginx/certs}"
ACTIVE="${TLS_ACTIVE_DIR:-/etc/nginx/tls}"
CRT="$MOUNTED/tls.crt"
KEY="$MOUNTED/tls.key"

mkdir -p "$ACTIVE"

if [ -f "$CRT" ] || [ -f "$KEY" ]; then
  # Half a pair is a mistake, not a request for the fallback: serving a
  # self-signed certificate when the operator believes they installed a real
  # one is exactly the failure nobody would notice.
  if [ ! -s "$CRT" ] || [ ! -s "$KEY" ]; then
    echo "[tls] ERROR: $MOUNTED must contain both tls.crt and tls.key, non-empty." >&2
    exit 1
  fi
  if [ ! -r "$KEY" ]; then
    echo "[tls] ERROR: $KEY is not readable by uid $(id -u). nginx runs unprivileged;" >&2
    echo "[tls]        make the key readable to that uid (chown, or chmod 0444 inside a 0700 directory)." >&2
    exit 1
  fi
  ln -sf "$CRT" "$ACTIVE/tls.crt"
  ln -sf "$KEY" "$ACTIVE/tls.key"
  echo "[tls] Using the certificate mounted at $MOUNTED."
  exit 0
fi

CN="${TLS_SELF_SIGNED_CN:-localhost}"
echo "[tls] ======================================================================"
echo "[tls] WARNING: no certificate mounted at $MOUNTED."
echo "[tls] Generating a SELF-SIGNED certificate for '$CN'. Traffic is encrypted,"
echo "[tls] but browsers will warn and nothing proves this server's identity."
echo "[tls] For anything but local use, mount tls.crt and tls.key (docs/OPERATIONS.md)."
echo "[tls] ======================================================================"

SAN="DNS:localhost,IP:127.0.0.1,IP:::1"
[ "$CN" = "localhost" ] || SAN="DNS:$CN,$SAN"

# -f: a previous run may have left links to a mount that is now gone.
rm -f "$ACTIVE/tls.crt" "$ACTIVE/tls.key"
( umask 077
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
    -keyout "$ACTIVE/tls.key" -out "$ACTIVE/tls.crt" \
    -subj "/CN=$CN" \
    -addext "subjectAltName=$SAN" \
    >/dev/null 2>&1 )
