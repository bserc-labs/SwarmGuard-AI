"""Rotate the passwords of named accounts, on the server whose database this is.

    docker compose exec -T backend python scripts/rotate_passwords.py --dry-run admin analyst
    (umask 077; docker compose exec -T backend python scripts/rotate_passwords.py \\
        admin analyst commander observer operator > rotated-$(hostname).tsv)

Written for the seed accounts whose password hashes were committed to git
history (reports/07-PHASE4-EXECUTION-PLAN.md, 4.5). Rewriting history does not
un-leak a hash someone has already cloned; a new password does.

There is deliberately no API route for this: an administrator may disable an
account but not choose its owner's secret (schemas.UserAdminUpdate). This runs
where the database is, as the operator of that server.

For each account:
  * a new random password (32 URL-safe characters), hashed as login does;
  * token_version bumped, so every session the account holds ends now;
  * a USER_PASSWORD_ROTATED audit row, with no secret in it.

All accounts are changed in one transaction, and each new password is checked
against the stored hash before anything is printed.

The passwords go to stdout as `username<TAB>password`, one per line, and ONLY
when stdout is not a terminal: redirect it into a file only you can read, hand
each password to its owner, then delete the file. Everything else goes to
stderr. An account that does not exist on this server is reported and skipped.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

import models
from services.audit_service import audit_service
from services.auth_service import get_password_hash, verify_password

ACTOR = "scripts/rotate_passwords.py"
ACTION = "USER_PASSWORD_ROTATED"


def new_password() -> str:
    return secrets.token_urlsafe(24)


def rotate(db: Session, usernames: list[str], *, reason: str) -> tuple[dict[str, str], list[str]]:
    """Set a new password on each existing account. Returns (rotated, missing).

    Commits once, for all of them; on any failure nothing is changed.
    """
    rotated: dict[str, str] = {}
    missing: list[str] = []
    try:
        for username in usernames:
            user = db.query(models.User).filter(models.User.username == username).first()
            if user is None:
                missing.append(username)
                continue
            password = new_password()
            user.password = get_password_hash(password)
            user.token_version = (user.token_version or 0) + 1
            audit_service.log(
                db,
                actor=ACTOR,
                action=ACTION,
                organization_id=user.organization_id,
                resource="user",
                resource_id=username,
                reason=reason,
                details="Password replaced and every session revoked.",
            )
            rotated[username] = password
        db.commit()
    except Exception:
        db.rollback()
        raise

    for username, password in rotated.items():
        user = db.query(models.User).filter(models.User.username == username).one()
        if not verify_password(password, user.password):
            raise RuntimeError(f"stored hash for {username} does not verify; investigate before using it")
    return rotated, missing


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, db: Session | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("usernames", nargs="+")
    parser.add_argument("--dry-run", action="store_true", help="say which accounts exist; change nothing")
    parser.add_argument("--reason", default="password hash exposed in git history")
    args = parser.parse_args(argv)

    if not args.dry_run and stdout.isatty():
        print(
            "refusing to print passwords to a terminal. Redirect stdout to a file only you "
            "can read, e.g. (umask 077; ... > rotated.tsv)",
            file=sys.stderr,
        )
        return 2

    if db is None:
        from database import SessionLocal

        session = SessionLocal()
    else:
        session = db
    try:
        if args.dry_run:
            for username in args.usernames:
                user = session.query(models.User).filter(models.User.username == username).first()
                state = "missing" if user is None else f"exists (org {user.organization_id}, {user.role})"
                print(f"{username}: {state}", file=sys.stderr)
            return 0

        rotated, missing = rotate(session, args.usernames, reason=args.reason)
    finally:
        if db is None:
            session.close()

    for username, password in rotated.items():
        stdout.write(f"{username}\t{password}\n")
    stdout.flush()
    print(f"rotated {len(rotated)}: {', '.join(rotated) or '-'}", file=sys.stderr)
    if missing:
        print(f"not on this server, skipped: {', '.join(missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
