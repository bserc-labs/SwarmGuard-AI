"""Refuse to serve against a database the code was not built for.

Migrations used to run on every container start, so "the schema matches the
code" was true by construction. They now run once, in a dedicated job, which
makes it possible for the API to come up *before* that job has finished, or
after it failed. New code on an old schema does not fail at boot: it fails on
whichever request first touches the missing column, an hour later, as a 500
that points nowhere near the cause.

So the API checks at startup and says what is wrong while someone is looking.

Three outcomes, and the asymmetry between the last two is deliberate:

  * at head        -- serve.
  * behind         -- refuse. The migrate job has not run, or failed.
  * ahead/unknown  -- warn and serve. This is what a rollback looks like: the
                      previous image started against a database the newer
                      release already migrated. Refusing here would turn every
                      rollback into an outage, which defeats the point of
                      having one. It is safe only because migrations are
                      required to stay backward compatible for one release
                      (docs/OPERATIONS.md).
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy.engine import Engine

BACKEND_DIR = Path(__file__).resolve().parent.parent

AT_HEAD = "at_head"
BEHIND = "behind"
AHEAD = "ahead"


class SchemaOutOfDate(RuntimeError):
    """The database is behind the migrations this build ships with."""


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # alembic.ini names the script location relative to the working directory;
    # the API is not guaranteed to be started from backend/.
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def expected_heads() -> set[str]:
    """The head revision(s) of the migration scripts in this build."""
    return set(_script_directory().get_heads())


def current_heads(engine: Engine) -> set[str]:
    """The revision(s) recorded in the database; empty if never migrated."""
    with engine.connect() as connection:
        return set(MigrationContext.configure(connection).get_current_heads())


def classify(current: set[str], expected: set[str], known) -> str:
    """Pure decision, separated so it can be tested without a database.

    `known(revision) -> bool` says whether this build has a script for it.
    """
    if current == expected:
        return AT_HEAD
    if any(not known(revision) for revision in current):
        return AHEAD
    return BEHIND


def _is_known(revision: str) -> bool:
    try:
        return _script_directory().get_revision(revision) is not None
    except CommandError:
        return False


def schema_state(engine: Engine) -> tuple[str, set[str], set[str]]:
    current, expected = current_heads(engine), expected_heads()
    return classify(current, expected, _is_known), current, expected


def assert_schema_current(engine: Engine, logger) -> str:
    """Raise SchemaOutOfDate if the database is behind; return the state."""
    state, current, expected = schema_state(engine)
    shown = ", ".join(sorted(current)) or "<never migrated>"
    wanted = ", ".join(sorted(expected))
    if state == BEHIND:
        raise SchemaOutOfDate(
            f"Database schema is at {shown} but this build requires {wanted}. "
            "Run the migrate job first (`docker compose run --rm migrate`, or "
            "`alembic upgrade head`). The API does not migrate on start: two "
            "replicas doing so together would run the same DDL concurrently."
        )
    if state == AHEAD:
        logger.warning(
            f"Database schema is at {shown}, which this build does not know; it "
            f"expects {wanted}. Serving anyway: this is what a rollback looks "
            "like, and it is safe only while migrations stay backward "
            "compatible for one release."
        )
    return state
