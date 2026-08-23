import logging
import uuid
from sqlalchemy.orm import Session
from models import AuditLog
from typing import Optional
from middleware.auth_middleware import TenantContext

logger = logging.getLogger(__name__)

class AuditService:
    def log(
        self,
        db: Session,
        actor: str,
        action: str,
        organization_id: Optional[int] = None,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        target: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> AuditLog:
        """
        Record an immutable, append-only audit trail entry for defense-grade traceability.
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

        # We don't commit here. Let the calling transaction commit
        # so that the incident creation and audit log are atomic.

        logger.info(f"Audit: {actor} (org:{organization_id}) performed {action} on {resource}:{resource_id} ({previous_state}->{new_state})")
        return audit

    def log_from_context(
        self,
        db: Session,
        tenant: TenantContext,
        action: str,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        target: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AuditLog:
        """Convenience method that extracts actor and org_id from TenantContext."""
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
        )

audit_service = AuditService()
