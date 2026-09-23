"""Per-device credentials for telemetry ingest.

Every drone used to present the same DRONE_API_KEY. One airframe lost, captured
or decommissioned without a wipe was the key for the whole fleet, and the only
remedy was re-keying every aircraft at the same moment -- so in practice it was
never done.

Each drone can now hold its own key:

  * Issued once, shown once. The response to the issuing call is the only time
    the plaintext exists outside the drone; the database stores its SHA-256.
    A 256-bit random key does not need a slow password hash -- there is nothing
    to brute-force -- and a plain digest lets ingest find the row in one
    indexed lookup instead of trying every hash in the fleet.
  * Bound to one drone in one organization. A key presented for a different
    drone id, or by a caller whose token is for another organization, is
    rejected; the second case is answered exactly like an unknown key, so a
    probe learns nothing about other tenants.
  * Revocable one at a time, and several may be live for the same drone, so a
    key can be rotated with overlap: issue the new one, load it, revoke the old.

The shared key keeps working behind DEVICE_SHARED_KEY_ENABLED so nothing breaks
on upgrade. The swarmguard_device_auth_total{method} metric says when the last
drone has stopped using it; then turn it off.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from models import DeviceCredential

KEY_PREFIX = "sgd_"
DISPLAY_PREFIX_LEN = 12
# last_used_at is a convenience for "which keys are still in use", not an audit
# trail; writing it on every packet would add a row update per packet at up to
# 50 packets a second. Once a minute is plenty to answer the question.
LAST_USED_RESOLUTION = timedelta(minutes=1)

# Rejection reasons, recorded on the audit row. The HTTP answer is the same for
# all of them so a caller cannot tell which it hit.
MISSING = "missing_api_key"
SHARED_MISMATCH = "invalid_api_key"
SHARED_DISABLED = "shared_key_disabled"
UNKNOWN = "unknown_device_key"
REVOKED = "revoked_device_key"
WRONG_DRONE = "device_key_for_other_drone"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class DeviceAuth:
    ok: bool
    method: str | None = None  # "device_key" | "shared_key"
    reason: str | None = None
    credential_id: int | None = None


def authenticate(
    db: Session,
    presented: str | None,
    *,
    organization_id: int,
    drone_id: str,
    shared_key: str,
    shared_key_enabled: bool,
    now: datetime | None = None,
) -> DeviceAuth:
    """Decide whether `presented` may send telemetry as `drone_id` for this organization."""
    if not presented:
        return DeviceAuth(False, reason=MISSING)

    if presented.startswith(KEY_PREFIX):
        credential = db.query(DeviceCredential).filter(DeviceCredential.key_hash == digest(presented)).first()
        if credential is None or credential.organization_id != organization_id:
            return DeviceAuth(False, reason=UNKNOWN)
        if credential.revoked_at is not None:
            return DeviceAuth(False, reason=REVOKED, credential_id=credential.id)
        if credential.drone_id != drone_id:
            return DeviceAuth(False, reason=WRONG_DRONE, credential_id=credential.id)
        moment = now or datetime.now(UTC)
        if credential.last_used_at is None or moment - credential.last_used_at >= LAST_USED_RESOLUTION:
            # Staged on the request's session; ingest commits it with the packet.
            credential.last_used_at = moment
        return DeviceAuth(True, method="device_key", credential_id=credential.id)

    if not shared_key_enabled:
        return DeviceAuth(False, reason=SHARED_DISABLED)
    # Constant time. `!=` on the secret leaked, one request at a time, how many
    # leading characters of a guess were right.
    if not hmac.compare_digest(presented.encode(), shared_key.encode()):
        return DeviceAuth(False, reason=SHARED_MISMATCH)
    return DeviceAuth(True, method="shared_key")


def issue(db: Session, *, organization_id: int, drone_id: str, issued_by: str, label: str | None) -> tuple[DeviceCredential, str]:
    """Create a credential and return it with the plaintext key, which is never stored."""
    key = generate_key()
    credential = DeviceCredential(
        organization_id=organization_id,
        drone_id=drone_id,
        key_hash=digest(key),
        key_prefix=key[:DISPLAY_PREFIX_LEN],
        label=label,
        created_by=issued_by,
    )
    db.add(credential)
    return credential, key


def revoke(credential: DeviceCredential, *, revoked_by: str, now: datetime | None = None) -> bool:
    """Revoke; False if it already was (revocation is not re-dated)."""
    if credential.revoked_at is not None:
        return False
    credential.revoked_at = now or datetime.now(UTC)
    credential.revoked_by = revoked_by
    return True
