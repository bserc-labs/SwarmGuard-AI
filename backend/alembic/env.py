from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

# `models` is imported for its side effect: defining the classes is what
# registers their tables on Base.metadata. Without it this file assigned an
# *empty* MetaData to target_metadata -- database.py declares Base and imports
# no models -- so autogenerate compared a live database against nothing.
#
# The next `alembic revision --autogenerate` would therefore have produced a
# migration whose upgrade() was op.drop_table() for every table in the schema,
# and it would have looked entirely routine in review.
import models  # noqa: F401
from database import DATABASE_URL, Base

# Set the target metadata
target_metadata = Base.metadata

# Set sqlalchemy url from our .env config dynamically
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# One migrator at a time.
#
# `alembic upgrade head` reads the current revision and then applies what is
# missing. Two of them starting together both read "nothing applied", and both
# run the same CREATE TABLE against the same database: one dies on "relation
# already exists", and which one -- and how far the other got -- is a matter of
# timing. That was the situation whenever two backend replicas started at once,
# because migrations ran from the container entrypoint.
#
# They now run from a single job, and this lock is what makes an overlap safe
# anyway: a rolling deploy that starts a second job, or a person at a terminal.
# It is a session-level advisory lock, taken before alembic looks at the
# version table, so the second migrator waits, then reads the revision the first
# one just committed and finds nothing to do. Session-level rather than
# transaction-level because it must outlive alembic's own transaction; it is
# released explicitly, and by the server if this process dies holding it.
#
# The key is arbitrary but must be the same for every migrator: "SGMI".
MIGRATION_LOCK_KEY = 0x53474D49


def run_migrations_online() -> None:
    """Run migrations in 'online' mode, serialised across processes."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        locked = connection.dialect.name == "postgresql"
        if locked:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
            # End the transaction the SELECT opened. Left open, alembic would
            # find the connection already in a transaction, decline to manage
            # it, and the migration would never be committed.
            connection.commit()
        try:
            context.configure(
                connection=connection, target_metadata=target_metadata
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
                )
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
