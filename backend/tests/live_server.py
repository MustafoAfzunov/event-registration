"""Real uvicorn processes for SSE tests (`uvicorn app.main:app --workers N`), pointed at the
test database. Writes made by the test process (in-process app) reach them only through
Postgres LISTEN/NOTIFY, so every live test is also a cross-process test."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LiveServer:
    url: str
    workers: int
    pids: frozenset[str]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@contextmanager
def run_server(env: dict[str, str], workers: int, log_path: Path) -> Iterator[LiveServer]:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    with log_path.open("w") as log:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv
            [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1", "--port", str(port),
                "--workers", str(workers), "--timeout-graceful-shutdown", "1",
            ],
            cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
        )  # fmt: skip
        try:
            pids = _wait_ready(url, workers, proc, log_path)
            yield LiveServer(url=url, workers=workers, pids=pids)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _wait_ready(url: str, workers: int, proc: subprocess.Popen[bytes], log: Path) -> frozenset[str]:
    """Until /health has been answered by `workers` distinct processes (fresh connection
    per probe, so the kernel can hand it to any worker)."""
    seen: set[str] = set()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn exited:\n{log.read_text()}")
        try:
            r = httpx.get(f"{url}/health", headers={"Connection": "close"}, timeout=2)
            if r.status_code == 200:
                seen.add(r.headers["x-backend-pid"])
                if len(seen) >= workers:
                    return frozenset(seen)
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"server not ready ({len(seen)}/{workers} workers):\n{log.read_text()}")


def server_env(test_db_url: str, organizer_password: str, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": test_db_url,
        "ORGANIZER_PASSWORD": organizer_password,
        "SESSION_SECRET": "test-session-secret-0123456789abcdef",
        "PUBLIC_BASE_URL": "http://app.test",
        "SSE_KEEPALIVE_SECONDS": "1",
        **extra,
    }
