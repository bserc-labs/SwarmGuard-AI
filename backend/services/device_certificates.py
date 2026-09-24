"""Client certificates for telemetry ingest: what nginx verified, and for whom.

A device key is a bearer secret. Whoever reads it off a recovered airframe
sends telemetry as that drone until someone notices and revokes it. A client
certificate's private key can live where a file cannot be copied from, and the
TLS handshake proves the caller holds it.

The handshake happens at nginx, on port 8443 (frontend/nginx.conf), which
refuses any caller without a certificate from the device CA that is not
revoked (scripts/device-ca.sh). What reaches the application is nginx's word
for it, in three headers set from the handshake:

    X-Device-Cert-Verify   SUCCESS
    X-Device-Cert-Subject  CN=<drone id>,O=org:<organization id>   (RFC 2253)
    X-Device-Cert-Serial   the certificate's serial, for the audit row

nginx did not check that the certificate belongs to the drone the packet names;
that is done here. A certificate for drone A cannot carry drone B's telemetry,
and one issued for one organization is refused by every other.

Why the headers can be believed: nginx sets them on 8443 and blanks them on 443
(a caller's own copies are dropped either way), and the backend's port is
published on the loopback interface only (tests/test_compose_config.py). Anyone
who can reach it directly is already on the host.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

VERIFY_HEADER = "x-device-cert-verify"
SUBJECT_HEADER = "x-device-cert-subject"
SERIAL_HEADER = "x-device-cert-serial"

VERIFIED = "verified"
ABSENT = "absent"
MISMATCH = "mismatch"

# Audit reasons, alongside services/device_credentials.py's.
REQUIRED = "client_certificate_required"
FOR_OTHER_DRONE = "client_certificate_for_other_drone"


@dataclass(frozen=True)
class CertificateCheck:
    outcome: str  # VERIFIED | ABSENT | MISMATCH
    subject: str | None = None
    serial: str | None = None


def organization_name(organization_id: int) -> str:
    """The O= a device certificate carries. scripts/device-ca.sh writes the same."""
    return f"org:{organization_id}"


def parse_dn(dn: str) -> dict[str, list[str]]:
    """RFC 2253 distinguished name to {attribute: [values]}.

    Handles backslash escapes, so a comma or plus inside a value (`CN=a\\,b`)
    is part of the value rather than a separator. Values are returned as
    written, unescaped. Multi-valued RDNs (`+`) are split like separate ones.
    """
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in dn:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch in ",+":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))

    fields: dict[str, list[str]] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        fields.setdefault(key.strip().upper(), []).append(value.strip())
    return fields


def check(headers: Mapping[str, str], *, organization_id: int, drone_id: str) -> CertificateCheck:
    """Whether this request came through the mTLS port with a certificate for this drone."""
    verify = headers.get(VERIFY_HEADER)
    subject = headers.get(SUBJECT_HEADER)
    serial = headers.get(SERIAL_HEADER)
    # ssl_verify_client on means nginx never forwards anything but SUCCESS. Any
    # other value is treated as no certificate, not as a softer yes.
    if verify != "SUCCESS" or not subject:
        return CertificateCheck(ABSENT)

    fields = parse_dn(subject)
    # Exactly one of each. A second CN would make "which drone is this" a
    # question of which one a parser reads first.
    if fields.get("CN") != [drone_id] or fields.get("O") != [organization_name(organization_id)]:
        return CertificateCheck(MISMATCH, subject=subject, serial=serial)
    return CertificateCheck(VERIFIED, subject=subject, serial=serial)
