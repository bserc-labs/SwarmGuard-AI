#!/bin/sh
# The certificate authority for drone client certificates (mTLS, port 8443).
#
#   scripts/device-ca.sh init                          create the CA, once
#   scripts/device-ca.sh issue <org-id> <drone-id> [days]   a certificate for one drone
#   scripts/device-ca.sh revoke <device.crt>           revoke one, and republish the CRL
#   scripts/device-ca.sh crl                           republish the CRL (monthly, from cron)
#   scripts/device-ca.sh list                          every certificate issued, with status
#
# A device key is a bearer secret: anyone who reads it off a recovered airframe
# can send telemetry as that drone until it is revoked. A client certificate's
# private key can live somewhere a key file cannot be copied from (a TPM, a
# secure element), and nginx refuses the TLS session of any caller that cannot
# prove it holds one -- before the application sees a byte.
#
# Layout, under $SWARMGUARD_DEVICE_CA_HOME (default ./device-ca):
#
#   private/   the CA key and its database. Keep this OFF the server: on the
#              machine that issues certificates, or better, offline. Nothing
#              the proxy needs is in here.
#   trust/     ca.crt and crl.pem: public. This is what the proxy mounts
#              ($SWARMGUARD_DEVICE_TRUST_DIR in docker-compose.yml).
#   issued/    one directory per certificate: device.key, device.crt, ca.crt.
#              Load them onto the drone, then delete the key from here.
#
# A certificate names its drone: subject O=org:<organization id>, CN=<drone id>.
# The API refuses a certificate presented for any other drone or organization.
#
# nginx refuses EVERY client once the CRL passes its nextUpdate, so `crl` must
# run before it expires (CRL_DAYS, default 30) and the proxy be reloaded:
#   scripts/device-ca.sh crl && docker compose exec frontend nginx -s reload
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${SWARMGUARD_DEVICE_CA_HOME:-$ROOT/device-ca}"
PRIVATE="$HOME_DIR/private"
TRUST="$HOME_DIR/trust"
ISSUED="$HOME_DIR/issued"
CONF="$PRIVATE/openssl.cnf"
CA_DAYS="${CA_DAYS:-3650}"
CRL_DAYS="${CRL_DAYS:-30}"

die() { echo "device-ca: $*" >&2; exit 1; }

need_ca() {
  [ -s "$PRIVATE/ca.key" ] && [ -s "$CONF" ] || die "no CA at $HOME_DIR; run '$0 init' first"
}

publish_crl() {
  openssl ca -config "$CONF" -gencrl -crldays "$CRL_DAYS" -out "$TRUST/crl.pem.tmp" 2>/dev/null
  # Renamed into place, so a proxy reloading at the wrong moment never reads
  # half a file.
  mv "$TRUST/crl.pem.tmp" "$TRUST/crl.pem"
  chmod 444 "$TRUST/crl.pem"
}

cmd_init() {
  if [ -e "$PRIVATE/ca.key" ]; then
    die "$PRIVATE/ca.key exists; refusing to replace a CA every device certificate chains to"
  fi
  mkdir -p "$PRIVATE" "$TRUST" "$ISSUED"
  chmod 700 "$PRIVATE" "$ISSUED"
  : > "$PRIVATE/index.txt"
  echo 1000 > "$PRIVATE/serial"
  echo 1000 > "$PRIVATE/crlnumber"
  cat > "$CONF" <<EOF
[ ca ]
default_ca = device_ca

[ device_ca ]
dir               = $PRIVATE
database          = \$dir/index.txt
serial            = \$dir/serial
crlnumber         = \$dir/crlnumber
new_certs_dir     = \$dir/newcerts
certificate       = $TRUST/ca.crt
private_key       = \$dir/ca.key
default_md        = sha256
default_crl_days  = $CRL_DAYS
policy            = device_policy
unique_subject    = no
copy_extensions   = none
email_in_dn       = no

[ device_policy ]
organizationName  = supplied
commonName        = supplied

[ device_cert ]
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid
EOF
  mkdir -p "$PRIVATE/newcerts"
  ( umask 077
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$PRIVATE/ca.key" 2>/dev/null )
  openssl req -x509 -new -key "$PRIVATE/ca.key" -sha256 -days "$CA_DAYS" \
    -subj "/O=SwarmGuard/CN=SwarmGuard device CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$TRUST/ca.crt" 2>/dev/null
  chmod 444 "$TRUST/ca.crt"
  publish_crl
  echo "Device CA created in $HOME_DIR."
  echo "  Mount $TRUST on the proxy (SWARMGUARD_DEVICE_TRUST_DIR), then keep $PRIVATE off the server."
}

cmd_issue() {
  [ $# -ge 2 ] || die "usage: $0 issue <organization-id> <drone-id> [days]"
  org="$1"; drone="$2"; days="${3:-365}"
  need_ca
  case "$org" in ''|*[!0-9]*) die "organization id must be a number, got '$org'" ;; esac
  # The drone id goes into a certificate subject and a directory name. Keep it
  # to what drone ids actually are, so neither can be abused.
  case "$drone" in ''|*[!A-Za-z0-9._-]*) die "drone id may contain only letters, digits, '.', '_' and '-'" ;; esac

  serial="$(cat "$PRIVATE/serial")"
  out="$ISSUED/org-$org/$drone-$serial"
  mkdir -p "$out"
  chmod 700 "$ISSUED/org-$org" "$out"
  ( umask 077
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$out/device.key" 2>/dev/null )
  openssl req -new -key "$out/device.key" -subj "/O=org:$org/CN=$drone" -out "$out/device.csr" 2>/dev/null
  openssl ca -batch -config "$CONF" -extensions device_cert -days "$days" -notext \
    -in "$out/device.csr" -out "$out/device.crt" 2>/dev/null \
    || die "issuing failed; see: openssl ca -config $CONF"
  rm -f "$out/device.csr"
  cp "$TRUST/ca.crt" "$out/ca.crt"
  echo "Issued serial $serial for drone '$drone' in organization $org, valid $days days:"
  echo "  $out/device.crt"
  echo "  $out/device.key   <- load onto the drone, then delete it here"
}

cmd_revoke() {
  [ $# -eq 1 ] || die "usage: $0 revoke <device.crt>"
  need_ca
  [ -s "$1" ] || die "no certificate at $1"
  openssl ca -config "$CONF" -revoke "$1" 2>/dev/null || die "revoking $1 failed (already revoked?)"
  publish_crl
  echo "Revoked $(openssl x509 -in "$1" -noout -subject -serial | tr '\n' ' ')"
  echo "Reload the proxy for it to take effect: docker compose exec frontend nginx -s reload"
}

cmd_crl() {
  need_ca
  publish_crl
  echo "Published $TRUST/crl.pem, valid $CRL_DAYS days. Reload the proxy: docker compose exec frontend nginx -s reload"
}

cmd_list() {
  need_ca
  # index.txt: status (V valid, R revoked, E expired), expiry, [revoked at], serial, file, subject.
  awk -F'\t' '{ printf "%s  serial %s  expires %s  %s\n", ($1=="V"?"valid  ":($1=="R"?"REVOKED":"expired")), $4, $2, $6 }' "$PRIVATE/index.txt"
}

command="${1:-}"
[ $# -gt 0 ] && shift
case "$command" in
  init) cmd_init "$@" ;;
  issue) cmd_issue "$@" ;;
  revoke) cmd_revoke "$@" ;;
  crl) cmd_crl "$@" ;;
  list) cmd_list "$@" ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
