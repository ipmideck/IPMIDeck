"""Per-connection WebSocket session-metadata tests (D-19).

Verifies WebSocketManager records remote IP + connect timestamp (+ optional User-Agent)
per live connection, drops the entry on disconnect, and exposes a console-only sessions()
accessor that returns FRESH copies (never the internal _session_meta dicts — REVIEWS LOW).
No real TTY/BMC/WebSocket transport is needed: a tiny fake WS mimics the starlette surface
(``ws.client.host`` + ``ws.headers``) the manager reads.

asyncio_mode="auto" (pyproject) => async tests need NO decorator.
"""

from __future__ import annotations

from backend.core.websocket import WebSocketManager


class _FakeClient:
    """Mimics starlette's Address namedtuple (only the .host we read)."""

    def __init__(self, host):
        self.host = host


class _FakeWS:
    """Minimal WebSocket double — accept()/send_text() + .client/.headers surface."""

    def __init__(self, host="10.0.0.5", ua="pytest-agent", client=...):
        # client=... sentinel => build a real fake client; pass client=None to simulate
        # a transport where ws.client is None (the fallback-to-"unknown" path).
        self.client = _FakeClient(host) if client is ... else client
        self.headers = {"user-agent": ua}
        self.sent: list[str] = []

    async def accept(self):
        pass

    async def send_text(self, data):
        self.sent.append(data)


async def test_connect_records_session_metadata():
    """connect() captures ip + connected_since + user_agent for the live client."""
    mgr = WebSocketManager()
    ws = _FakeWS(host="10.0.0.5", ua="pytest-agent")
    await mgr.connect(ws)

    sessions = mgr.sessions()
    assert len(sessions) == 1
    assert sessions[0]["ip"] == "10.0.0.5"
    assert sessions[0]["user_agent"] == "pytest-agent"
    # connected_since is present and an ISO-8601 string.
    assert "connected_since" in sessions[0]
    assert isinstance(sessions[0]["connected_since"], str)
    assert sessions[0]["connected_since"]  # non-empty
    # count stays consistent with the accessor.
    assert mgr.connection_count == 1 == len(sessions)


async def test_disconnect_drops_session():
    """disconnect() removes the metadata entry and decrements the count."""
    mgr = WebSocketManager()
    ws = _FakeWS()
    await mgr.connect(ws)
    mgr.disconnect(ws)

    assert mgr.sessions() == []
    assert mgr.connection_count == 0


async def test_missing_client_falls_back_to_unknown():
    """A connection whose ws.client is None does not crash; ip => 'unknown'."""
    mgr = WebSocketManager()
    ws = _FakeWS(client=None)
    await mgr.connect(ws)

    sessions = mgr.sessions()
    assert len(sessions) == 1
    assert sessions[0]["ip"] == "unknown"


async def test_sessions_returns_copies_not_internal():
    """Mutating a returned dict must NOT leak into the manager's internal meta."""
    mgr = WebSocketManager()
    ws = _FakeWS(host="10.0.0.5")
    await mgr.connect(ws)

    first = mgr.sessions()
    first[0]["ip"] = "tampered"

    second = mgr.sessions()
    assert second[0]["ip"] == "10.0.0.5"  # internal state unaffected
    assert second[0] is not first[0]  # fresh dict each call
