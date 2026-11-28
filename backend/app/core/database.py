from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import DATABASE_URL

# BUG FIX [2026-11-28]: Prevent sqlite3.OperationalError: database is locked under concurrent multi-threaded requests
# Root cause: SQLite defaulted to DELETE journal mode and a 5s lock timeout, blocking concurrent readers/writers.
# Fix: Set 30s connection timeout and enable WAL mode, busy_timeout=30000, synchronous=NORMAL, and foreign_keys=ON on connect.
# Watch for: SQLite -wal/-shm sidecar files in the data directory; concurrent write contention if moving to multi-process workers.
_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
