"""The telemetry retention policy, as seen from the application.

Retention itself is TimescaleDB's job (migration k1f2a3b4c5d6): a policy that
drops chunks older than three days, run by the database's background workers.
The application no longer deletes anything. What it does keep is a supervised
loop that asks, once an hour, whether that policy exists and last ran
successfully -- because a policy someone removed by hand, or a database
restored from a dump that predates it, would otherwise let the table grow
without anyone noticing until the disk did.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

TABLE = "telemetry_logs"


class RetentionPolicyMissing(RuntimeError):
    """No retention policy on telemetry_logs: the table will grow without bound."""


class RetentionPolicyFailing(RuntimeError):
    """The policy exists but its last run failed."""


@dataclass(frozen=True)
class RetentionPolicy:
    job_id: int
    drop_after: str
    schedule_interval: timedelta
    chunk_interval: timedelta
    last_run_status: str | None
    last_successful_finish: datetime | None
    total_runs: int
    total_failures: int


def retention_policy(db: Session) -> RetentionPolicy | None:
    row = db.execute(
        text(
            """
            SELECT j.job_id,
                   j.config ->> 'drop_after'        AS drop_after,
                   j.schedule_interval,
                   d.time_interval                  AS chunk_interval,
                   s.last_run_status,
                   s.last_successful_finish,
                   coalesce(s.total_runs, 0)        AS total_runs,
                   coalesce(s.total_failures, 0)    AS total_failures
              FROM timescaledb_information.jobs j
              LEFT JOIN timescaledb_information.job_stats s ON s.job_id = j.job_id
              LEFT JOIN timescaledb_information.dimensions d
                     ON d.hypertable_name = j.hypertable_name AND d.dimension_number = 1
             WHERE j.proc_name = 'policy_retention' AND j.hypertable_name = :table
             ORDER BY j.job_id
             LIMIT 1
            """
        ),
        {"table": TABLE},
    ).mappings().first()
    if row is None:
        return None
    return RetentionPolicy(
        job_id=row["job_id"],
        drop_after=row["drop_after"],
        schedule_interval=row["schedule_interval"],
        chunk_interval=row["chunk_interval"],
        last_run_status=row["last_run_status"],
        last_successful_finish=row["last_successful_finish"],
        total_runs=row["total_runs"],
        total_failures=row["total_failures"],
    )


def check_retention_policy(db: Session) -> RetentionPolicy:
    """The supervised loop's pass: raise if retention is not happening."""
    policy = retention_policy(db)
    if policy is None:
        raise RetentionPolicyMissing(
            f"{TABLE} has no retention policy. Apply migration k1f2a3b4c5d6, or "
            f"SELECT add_retention_policy('{TABLE}', INTERVAL '3 days')."
        )
    if policy.last_run_status == "Failed":
        raise RetentionPolicyFailing(
            f"retention policy job {policy.job_id} on {TABLE} failed its last run "
            f"({policy.total_failures} failure(s) in {policy.total_runs} runs); "
            "see timescaledb_information.job_errors"
        )
    return policy
