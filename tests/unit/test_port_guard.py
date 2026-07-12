"""Single-instance port-guard tests (D-17).

port_in_use() must report True when a socket is already listening and False when the port is
free, WITHOUT SO_REUSEADDR (RESEARCH Pitfall 4). Pure localhost sockets — the real BMC
(192.0.2.110) is never touched.
"""

from __future__ import annotations

import socket

from backend.console import port_in_use


def test_port_in_use_false_when_free():
    """A port that nothing is listening on reports False."""
    # Grab an OS-assigned free port, read it, then CLOSE it so it is genuinely free.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    assert port_in_use("127.0.0.1", free_port) is False


def test_port_in_use_true_when_listening():
    """A port with a live listening socket reports True."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    taken_port = listener.getsockname()[1]
    try:
        assert port_in_use("127.0.0.1", taken_port) is True
    finally:
        listener.close()
