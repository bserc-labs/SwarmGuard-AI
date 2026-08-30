"""
Single authoritative provisioning path for SwarmGuard AI.

Creates the default Organization and the initial admin user in one transaction.
Both are required: a user without an organization_id is rejected by
get_tenant_context on every protected route, so an admin created without one
can authenticate and then do nothing.

Idempotent — safe to run on every container start.

Usage:
    ADMIN_USERNAME=... ADMIN_PASSWORD=... python bootstrap.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

import models
from database import SessionLocal
from services.auth_service import get_password_hash
from utils.logger import logger

DEFAULT_ORG_NAME = os.getenv("DEFAULT_ORG_NAME", "SwarmGuard Default")
DEFAULT_ORG_SLUG = os.getenv("DEFAULT_ORG_SLUG", "swarmguard-default")
MIN_PASSWORD_LENGTH = 12


def get_or_create_default_organization(db) -> models.Organization:
    """Return the default organization, creating it if absent."""
    org = (
        db.query(models.Organization)
        .filter(models.Organization.slug == DEFAULT_ORG_SLUG)
        .first()
    )
    if org:
        return org

    org = models.Organization(
        name=DEFAULT_ORG_NAME,
        slug=DEFAULT_ORG_SLUG,
        status="ACTIVE",
    )
    db.add(org)
    db.flush()  # assign org.id without committing — caller owns the transaction
    logger.info(f"Created organization '{org.name}' (slug={org.slug})")
    return org


def bootstrap(username: str, password: str, email: str | None = None) -> None:
    """Create the default organization and an admin user bound to it."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters "
            f"(got {len(password)})."
        )

    db = SessionLocal()
    try:
        org = get_or_create_default_organization(db)

        existing = (
            db.query(models.User)
            .filter(models.User.username == username)
            .first()
        )

        if existing:
            # Repair the case this bootstrap exists to prevent: an admin that
            # predates multi-tenancy and is locked out of every route.
            if existing.organization_id is None:
                existing.organization_id = org.id
                db.commit()
                logger.info(
                    f"Admin '{username}' existed without an organization; "
                    f"assigned to '{org.slug}'."
                )
            else:
                logger.info(f"Admin '{username}' already provisioned. Nothing to do.")
            return

        admin = models.User(
            username=username,
            email=email or f"{username}@{DEFAULT_ORG_SLUG}.local",
            password=get_password_hash(password),
            role="admin",
            organization_id=org.id,
        )
        db.add(admin)
        db.commit()
        logger.info(f"Provisioned admin '{username}' in organization '{org.slug}'.")

    except (SQLAlchemyError, ValueError):
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")

    if not username or not password:
        print(
            "ERROR: ADMIN_USERNAME and ADMIN_PASSWORD must both be set.\n"
            "  export ADMIN_USERNAME=admin\n"
            "  export ADMIN_PASSWORD=$(openssl rand -base64 24)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        bootstrap(username, password, email=os.getenv("ADMIN_EMAIL"))
    except Exception as exc:
        print(f"ERROR: bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
