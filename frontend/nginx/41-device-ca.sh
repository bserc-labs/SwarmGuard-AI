#!/bin/sh
# Runs from /docker-entrypoint.d before nginx starts, after 40-tls.sh. Makes
# sure /etc/nginx/tls/device-ca.crt and device-crl.pem exist, which the device
# server in nginx.conf (port 8443, mTLS) points at.
#
#   trust mounted at /etc/nginx/device-ca  ->  link to its ca.crt and crl.pem
#   nothing mounted                        ->  a CA nobody holds the key to
#
# The mount is scripts/device-ca.sh's trust/ directory: a public certificate
# and a revocation list. The CA's private key is never on this machine.
#
# With nothing mounted the device port must still start -- nginx refuses to run
# without a client CA file -- and must admit no one. So a CA is generated here
# and its key thrown away on the spot: nothing can ever chain to it, and every
# client on 8443 is refused. Telemetry keeps flowing over 443 with device keys
# until an operator sets mTLS up.
set -eu

MOUNTED="${DEVICE_CA_DIR:-/etc/nginx/device-ca}"
ACTIVE="${TLS_ACTIVE_DIR:-/etc/nginx/tls}"
CRT="$MOUNTED/ca.crt"
CRL="$MOUNTED/crl.pem"

mkdir -p "$ACTIVE"

if [ -f "$CRT" ] || [ -f "$CRL" ]; then
  # Half is a mistake. Without the CRL a revoked drone would be let in, which
  # is the one thing revocation exists to prevent.
  if [ ! -s "$CRT" ] || [ ! -s "$CRL" ]; then
    echo "[device-ca] ERROR: $MOUNTED must contain both ca.crt and crl.pem, non-empty." >&2
    echo "[device-ca]        scripts/device-ca.sh init writes both into its trust/ directory." >&2
    exit 1
  fi
  # Read the verdict, not just the exit code: OpenSSL 3.0 prints "verify
  # failure" for a CRL signed by another key and still exits 0 (CI's Ubuntu
  # caught this; 3.6 exits 1). Both print "verify OK" only on a real match.
  verdict="$(openssl crl -in "$CRL" -noout -CAfile "$CRT" 2>&1)" || verdict="failed: $verdict"
  case "$verdict" in
    failed:*|*"verify failure"*) signed=no ;;
    *"verify OK"*) signed=yes ;;
    *) signed=no ;;
  esac
  if [ "$signed" != yes ]; then
    echo "[device-ca] ERROR: $CRL is not a revocation list signed by $CRT." >&2
    exit 1
  fi
  # nginx refuses every client certificate once the CRL is past nextUpdate. Say
  # so at start rather than leave an operator to find out from the drones.
  next="$(openssl crl -in "$CRL" -noout -nextupdate 2>/dev/null | sed 's/^nextUpdate=//')"
  echo "[device-ca] Using the device CA mounted at $MOUNTED. CRL valid until: $next"
  echo "[device-ca] Republish it before then: scripts/device-ca.sh crl, then nginx -s reload."
  ln -sf "$CRT" "$ACTIVE/device-ca.crt"
  ln -sf "$CRL" "$ACTIVE/device-crl.pem"
  exit 0
fi

echo "[device-ca] No device CA mounted at $MOUNTED: port 8443 (mTLS ingest) will refuse"
echo "[device-ca] every client. Drones keep ingesting over 443 with their device keys."
echo "[device-ca] To enable it: scripts/device-ca.sh init, then mount its trust/ directory."

rm -f "$ACTIVE/device-ca.crt" "$ACTIVE/device-crl.pem"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
( umask 077
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$WORK/ca.key" 2>/dev/null
  openssl req -x509 -new -key "$WORK/ca.key" -sha256 -days 3650 \
    -subj "/CN=SwarmGuard device CA (unconfigured, admits no one)" \
    -out "$ACTIVE/device-ca.crt" 2>/dev/null
  # An empty CRL, because nginx.conf names one. Signed with the same key, which
  # is then deleted with the rest of $WORK.
  : > "$WORK/index.txt"
  echo 1000 > "$WORK/crlnumber"
  printf '[ca]\ndefault_ca=c\n[c]\ndatabase=%s\ncrlnumber=%s\ndefault_md=sha256\n' \
    "$WORK/index.txt" "$WORK/crlnumber" > "$WORK/ca.cnf"
  openssl ca -config "$WORK/ca.cnf" -gencrl -crldays 3650 \
    -keyfile "$WORK/ca.key" -cert "$ACTIVE/device-ca.crt" -out "$ACTIVE/device-crl.pem" 2>/dev/null )
chmod 444 "$ACTIVE/device-ca.crt" "$ACTIVE/device-crl.pem"
