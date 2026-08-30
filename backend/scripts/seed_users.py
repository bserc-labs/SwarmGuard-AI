"""
Development seeding helper.

Delegates to bootstrap.py so there is exactly one provisioning path. This script
deliberately does NOT call Base.metadata.create_all(): building the schema
outside Alembic leaves no version stamp and, more importantly, no TimescaleDB
hypertable on telemetry_logs. Run migrations first:

    alembic upgrade head
    ADMIN_USERNAME=admin ADMIN_PASSWORD=<24+ chars> python scripts/seed_users.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bootstrap import main

if __name__ == "__main__":
    if not os.getenv("ADMIN_USERNAME") or not os.getenv("ADMIN_PASSWORD"):
        print(
            "ADMIN_USERNAME and ADMIN_PASSWORD must be set.\n"
            "Hardcoded admin/admin credentials were removed deliberately.",
            file=sys.stderr,
        )
        sys.exit(1)
    main()
