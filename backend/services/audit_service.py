import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from middleware.auth_middleware import TenantContext
from models import AuditLog

logger = logging.getLogger(__name__)

def purge_expired_audit_logs(db: Session, retention_days: int) -> int:
    """Delete audit rows older than `retention_days`; return how many.

    audit_logs rejects DELETE unless the session has announced a maintenance
    pass (migration e5f6a7b8c9d0), so this is the one place in the application
    that announces one, and it announces it for exactly one statement. A
    retention of 0 means keep everything and deletes nothing.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    db.execute(text("SET LOCAL swarmguard.audit_maintenance = 'on'"))
    result = db.execute(
        text("DELETE FROM audit_logs WHERE created_at < :cutoff"), {"cutoff": cutoff}
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


class AuditService:
    def log(
        self,
        db: Session,
        actor: str,
        action: str,
        organization_id: int | None = None,
        resource: str | None = None,
        resource_id: str | None = None,
        target: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        reason: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
        correlation_id: str | None = None,
        commit: bool = False,
    ) -> AuditLog:
        """Record an append-only audit trail entry.

        **This method stages a row; by default it does not commit it.** The
        caller owns the transaction, so that an audit entry and the action it
        describes land together or not at all.

        That contract is easy to violate silently, and was: `/telemetry/ingest`
        called this after `telemetry_service.process_telemetry` had already
        committed the packet, then returned. `get_db`'s `finally: db.close()`
        rolled the staged INSERT back, so every device-authenticated ingest --
        the highest-volume security-relevant event in the system -- produced no
        audit record at all. 315 ingests, 0 rows. Nothing failed loudly.

        Two things now guard against a repeat:

        * `commit=True` for callers that have nothing else to commit, notably
          those that raise immediately afterwards (a rejected device key must
          still be recorded even though the request ends in a 403).
        * `tests/test_audit_persistence.py`, which asserts that the rows this
          service is asked to write are actually readable from a new session.

        Pass `commit=True` only when this row is the whole transaction. When it
        accompanies another write, leave it False and let that write commit.
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())

        audit = AuditLog(
            actor=actor,
            organization_id=organization_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            target=target,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            details=details,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )
        db.add(audit)

        # By default the calling transaction commits, so that the action and
        # its audit entry are atomic. See the docstring for why this is not the
        # default everywhere.
        if commit:
            db.commit()

        logger.info(f"Audit: {actor} (org:{organization_id}) performed {action} on {resource}:{resource_id} ({previous_state}->{new_state})")
        return audit

    def log_from_context(
        self,
        db: Session,
        tenant: TenantContext,
        action: str,
        resource: str | None = None,
        resource_id: str | None = None,
        target: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        reason: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
        correlation_id: str | None = None,
        commit: bool = False,
    ) -> AuditLog:
        """Convenience method that extracts actor and org_id from TenantContext.

        Stages rather than commits, exactly as `log` does. See its docstring.
        """
        return self.log(
            db=db,
            actor=tenant.username,
            action=action,
            organization_id=tenant.organization_id,
            resource=resource,
            resource_id=resource_id,
            target=target,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            details=details,
            ip_address=ip_address,
            correlation_id=correlation_id,
            commit=commit,
        )

audit_service = AuditService()
