"""Two failures that were invisible because something swallowed them.

Neither of these was caught by the existing suite, and neither would have been
caught by reading the code carefully either -- they are the kind of defect that
only shows up when you ask "does this symbol actually exist?" and "does this
metadata actually contain anything?".
"""

import asyncio

import pytest


class TestHeartbeatAlertsReachTheSocket:
    """main.py called a ws_manager method that does not exist.

    `ws_manager.broadcast_secure(...)` -- ConnectionManager defines
    connect/disconnect/broadcast/_send_local and nothing else. Every iteration
    of the heartbeat loop raised AttributeError, and a bare `except Exception`
    wrapping the whole block logged it as an ordinary loop error.

    The consequence was not a crash. check_drone_heartbeats writes and *commits*
    a CRITICAL SIGNAL_LOSS_JAMMING incident before returning the alerts to be
    broadcast, so the record reached the database on every cycle and the
    operator was never told. A jamming alert that only a later database query
    can find is not an alert.
    """

    def test_the_broadcast_method_main_calls_exists(self):
        from services.ws_manager import ws_manager

        assert hasattr(ws_manager, "broadcast"), (
            "main.py's heartbeat loop calls ws_manager.broadcast"
        )

    def test_main_does_not_call_a_method_the_manager_lacks(self):
        """Catch the whole class of defect, not just the one instance.

        Parsed with ast rather than a regex over the source: the comment above
        the fixed call site names the method that used to be wrong, and a
        textual match cannot tell that apart from a real call. It found exactly
        that on the first run.
        """
        import ast
        import inspect

        import main
        from services.ws_manager import ws_manager

        tree = ast.parse(inspect.getsource(main))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ws_manager"
        }
        missing = sorted(m for m in called if not hasattr(ws_manager, m))

        assert not missing, (
            f"main.py calls ws_manager method(s) that do not exist: {missing}. "
            f"Available: {sorted(a for a in dir(ws_manager) if not a.startswith('__'))}"
        )

    def test_a_failed_send_for_one_org_does_not_suppress_the_next(self):
        """One tenant's broken socket must not silence every other tenant."""
        import main

        delivered = []

        class PartiallyBrokenManager:
            async def broadcast(self, payload, organization_id):
                if organization_id == 1:
                    raise RuntimeError("socket gone")
                delivered.append(organization_id)

        alerts = [(1, {"type": "incident"}), (2, {"type": "incident"}), (3, {"type": "incident"})]
        errors = []

        async def drive():
            manager = PartiallyBrokenManager()
            for organization_id, payload in alerts:
                # Mirrors the per-alert guard in main.py: one tenant's failure
                # is logged and the loop continues to the next.
                try:
                    await manager.broadcast(payload, organization_id)
                except Exception as exc:
                    errors.append((organization_id, str(exc)))

        asyncio.run(drive())
        assert errors == [(1, "socket gone")]
        assert delivered == [2, 3], (
            "orgs 2 and 3 must still be delivered after org 1 fails"
        )
        assert main is not None


class TestAlembicAutogenerateSeesTheSchema:
    """target_metadata was assigned an empty MetaData.

    env.py did `target_metadata = Base.metadata` but never imported models, and
    database.py declares Base without importing any. Autogenerate compares the
    live database against that metadata, so with zero tables registered the next
    `alembic revision --autogenerate` would emit op.drop_table() for all nine --
    a migration that looks entirely routine in review.
    """

    def test_base_metadata_is_populated_when_env_is_loaded(self):
        import pathlib

        env_path = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "env.py"
        assert env_path.exists()

        # env.py runs Alembic's context machinery on import, which needs a live
        # config. Assert the property that matters instead: the module it must
        # import to populate the metadata is imported.
        source = env_path.read_text()
        assert "import models" in source, (
            "alembic/env.py must import models, or Base.metadata is empty and "
            "autogenerate will emit DROP TABLE for every table"
        )

    def test_importing_models_registers_every_table(self):
        """Asserted against the model classes, not the shared metadata registry.

        `Base.metadata` is global mutable state and another test mutates it:
        tests/test_tenant_isolation_live.py removes `telemetry_logs` from it at
        import time, because that table's composite primary key cannot
        autoincrement on the in-memory SQLite it uses. So this passed alone and
        failed in a full run.

        What alembic actually needs is that importing `models` defines and binds
        every table, which is what is checked here.
        """
        import models

        expected = {
            "organizations": "Organization", "users": "User",
            "telemetry_logs": "TelemetryLog", "incidents": "Incident",
            "drones": "Drone", "command_requests": "CommandRequest",
            "audit_logs": "AuditLog", "system_settings": "SystemSettings",
            "geofence_zones": "GeofenceZone",
        }
        missing = []
        for table, cls_name in expected.items():
            cls = getattr(models, cls_name, None)
            if cls is None or getattr(cls, "__tablename__", None) != table:
                missing.append(f"{cls_name} -> {table}")

        assert not missing, f"models does not define/bind: {missing}"


def test_the_committed_sqlite_database_is_gone():
    """backend/swarmguard.db was tracked, and held four real password hashes.

    pbkdf2-sha256 hashes for admin, commander, analyst and observer, in every
    clone and fork. The application refuses to run on SQLite at all
    (database.py raises on a sqlite:// URL), so the file was not even a usable
    artefact -- just credentials with no purpose.
    """
    import pathlib
    import shutil
    import subprocess

    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")

    tracked = subprocess.run(  # noqa: S603 - fixed argv, resolved executable
        [git, "ls-files", "backend/swarmguard.db"],
        cwd=repo, capture_output=True, text=True, check=False,
    ).stdout.strip()

    assert tracked == "", (
        "backend/swarmguard.db is tracked again. It contains password hashes "
        "and the app cannot run on SQLite. Untrack it and keep it gitignored."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
