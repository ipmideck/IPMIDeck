"""Single-instance port-guard tests.

bind_problem() makes the one bind attempt cli() relies on: PORT_IN_USE when a socket is already
listening, ADDRESS_UNAVAILABLE when the address cannot be bound at all, None when the server can
start. On Linux it sets SO_REUSEADDR, so a port left in TIME_WAIT by the previous run does not
block a restart; elsewhere that option would let the probe bind over a live listener, so it stays
off. Localhost and RFC 5737 documentation addresses only.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

from backend.console import ADDRESS_UNAVAILABLE, PORT_IN_USE, bind_problem, port_in_use


def _listener(host="127.0.0.1", family=socket.AF_INET):
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.bind((host, 0))
    listener.listen(1)
    return listener, listener.getsockname()[1]


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


def test_a_running_wildcard_instance_is_detected():
    """A server on 0.0.0.0 is seen by the next one starting on 0.0.0.0 (Windows would let a
    127.0.0.1 probe bind over it)."""
    listener, port = _listener("0.0.0.0")
    try:
        assert bind_problem("0.0.0.0", port) == PORT_IN_USE
    finally:
        listener.close()


@pytest.mark.parametrize("host", ["192.0.2.1", "no-such-host.invalid"])
def test_an_address_this_host_cannot_bind_is_not_reported_as_in_use(host):
    assert bind_problem(host, 3000) == ADDRESS_UNAVAILABLE
    assert port_in_use(host, 3000) is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="TIME_WAIT reuse is Linux-only")
def test_port_left_in_time_wait_is_not_in_use():
    """A port whose last connection the server closed (TIME_WAIT) is free to start on again."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # As uvicorn does. Linux lets a new bind reuse a TIME_WAIT port only when the socket that
    # left it had SO_REUSEADDR too.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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


def _run_cli(tmp_path, host, port):
    env = dict(os.environ, IPMIDECK_DATA_DIR=str(tmp_path), IPMIDECK_DEMO="true")
    return subprocess.run(
        [sys.executable, "-m", "backend.main", "--host", host, "--port", str(port), "start"],
        env=env, capture_output=True, text=True, timeout=60,
    )


def test_cli_refuses_a_port_another_instance_holds(tmp_path):
    listener, port = _listener()
    try:
        result = _run_cli(tmp_path, "127.0.0.1", port)
    finally:
        listener.close()
    assert result.returncode == 1
    assert "already in use" in result.stderr


def test_cli_names_an_unusable_address_as_such(tmp_path):
    result = _run_cli(tmp_path, "192.0.2.1", 3000)
    assert result.returncode == 1
    assert "address unavailable or not permitted" in result.stderr
    assert "already in use" not in result.stderr
