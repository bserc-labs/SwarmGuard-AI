from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Resolve path to project root .env
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
from config import get_settings

settings = get_settings()
DATABASE_URL = settings.DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError("CRITICAL ERROR: DATABASE_URL is missing. Please ensure the .env file exists in the project root and defines DATABASE_URL.")


if DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("CRITICAL ERROR: SwarmGuard AI Enterprise requires PostgreSQL/TimescaleDB. SQLite is no longer supported.")

# Alembic handles TimescaleDB extension and hypertable creation via migrations.

# Pool sizing is explicit because ingest needs *two* connections per packet,
# not one: the request's own session, plus a second that the background
# detection task opens (services/detection_pipeline._detect_sync) and holds
# concurrently while it reads its telemetry window.
#
# SQLAlchemy's defaults (pool_size=5, max_overflow=10) cap that at 15. A load
# test at 80 concurrent senders exhausted the pool and every request blocked
# for the full 30 s checkout timeout:
#
#   QueuePool limit of size 5 overflow 10 reached, connection timed out
#
# The route is rate limited at 50 req/s, so the pool has to comfortably clear
# 2x that plus headroom. 20 + 40 = 60 stays well inside PostgreSQL's default
# max_connections of 100 for a single backend instance -- raise
# DB_POOL_SIZE/DB_MAX_OVERFLOW together with max_connections if running
# several workers.
#
# pool_timeout is short on purpose: under genuine saturation, failing fast
# surfaces the problem as an error the caller can retry, rather than holding a
# request open for 30 s until the client gives up first and the cause stays
# invisible.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()