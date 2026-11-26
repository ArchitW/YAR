"""In-memory log ring buffer and live subscriber fan-out for frontend terminal view."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any


class LogStreamHandler(logging.Handler):
    """Captures Python/Uvicorn log records into a ring buffer and notifies SSE subscribers."""

    def __init__(self, maxlen: int = 400) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = set()
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
            with self._lock:
                self._buffer.append(entry)
                subs = list(self._subscribers)
            for loop, q in subs:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(q.put_nowait, entry)
        except Exception:
            pass

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._buffer)
        return items[-limit:]

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add((loop, q))
        return q

    def unsubscribe(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard((loop, q))


log_stream_handler = LogStreamHandler()
log_stream_handler.setFormatter(logging.Formatter("%(message)s"))


def install_log_stream_handler() -> None:
    """Attach the log stream handler to root and uvicorn loggers once."""
    root = logging.getLogger()
    if log_stream_handler not in root.handlers:
        root.addHandler(log_stream_handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        if log_stream_handler not in lg.handlers:
            lg.addHandler(log_stream_handler)
