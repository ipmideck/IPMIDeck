"""Single-instance port-guard tests.

port_in_use() must report True when a socket is already listening and False when the port is
free. On Windows it binds WITHOUT SO_REUSEADDR, which would let a second socket bind over a
live listener; on POSIX it sets it, so a port left in TIME_WAIT by the previous run does not
block a restart. Pure localhost sockets — the real BMC (192.0.2.110) is never touched.
"""

from __future__ import annotations

import socket
import sys

import pytest

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


@pytest.mark.skipif(sys.platform == "win32", reason="TIME_WAIT reuse is the POSIX behaviour")
def test_port_left_in_time_wait_is_not_in_use():
    """A port whose last connection the server closed (TIME_WAIT) is free to start on again."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = listener.accept()
    conn.close()  # server side closes first -> server side goes to TIME_WAIT
    client.recv(1)
    client.close()
    listener.close()
    assert port_in_use("127.0.0.1", port) is False


def test_ipv6_listener_is_detected():
    """An IPv6 bind host is probed with an IPv6 socket instead of always reporting in use."""
    if not socket.has_ipv6:
        pytest.skip("no IPv6 on this host")
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.bind(("::1", 0))
    except OSError:
        listener.close()
        pytest.skip("::1 is not configured on this host")
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert port_in_use("::1", port) is True
    finally:
        listener.close()
    assert port_in_use("::1", port) is False
