"""Shared pytest fixtures."""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from taskboard5_api.main import app
from taskboard5_api.tasks import TaskStore


@pytest.fixture(scope="session", autouse=True)
def database_url() -> Iterator[str]:
    """A reachable Postgres URL; also exported as DATABASE_URL."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        os.environ["DATABASE_URL"] = external
        yield external
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        url = container.get_connection_url()
        os.environ["DATABASE_URL"] = url
        yield url


@pytest.fixture()
def empty_database(database_url: str) -> str:
    """Ensure the tasks table exists and is empty."""
    TaskStore(database_url).ensure_schema()
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE tasks RESTART IDENTITY")
    return database_url


class DatabaseSwitch:
    """A local TCP relay to the test database that can be cut and restored."""

    def __init__(self, target_host: str, target_port: int, database_url: str) -> None:
        self._target = (target_host, target_port)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port: int = probe.getsockname()[1]
        probe.close()
        info = conninfo_to_dict(database_url)
        info["host"] = "127.0.0.1"
        info["port"] = str(self.port)
        info.pop("hostaddr", None)
        self.url = make_conninfo(**info)
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._conns: list[socket.socket] = []
        self.restore()

    def restore(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", self.port))
            sock.listen(16)
            self._listener = sock
        threading.Thread(target=self._accept, args=(sock,), daemon=True).start()

    def cut(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
            conns, self._conns = self._conns, []
        if listener is not None:
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        for conn in conns:
            self._close(conn)

    stop = cut

    @staticmethod
    def _close(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(self._target, timeout=5)
                upstream.settimeout(None)
            except OSError:
                client.close()
                continue
            with self._lock:
                if self._listener is not listener:
                    client.close()
                    upstream.close()
                    return
                self._conns.extend([client, upstream])
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pump, args=(src, dst), daemon=True).start()

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            self._close(src)
            self._close(dst)


@pytest.fixture()
def db_outage(database_url: str) -> Iterator[DatabaseSwitch]:
    """A relay to the test database that tests can cut and restore."""
    info = conninfo_to_dict(database_url)
    switch = DatabaseSwitch(
        str(info.get("host") or "localhost"), int(info.get("port") or 5432), database_url
    )
    try:
        yield switch
    finally:
        switch.restore()
        switch.cut()


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)
