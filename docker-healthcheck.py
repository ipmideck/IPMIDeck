"""Container health probe: is the dashboard answering, over whichever scheme it came up on?

The probe cannot assume http. Once `IPMIDECK_SERVER_HTTPS` (or the `https` key in
config.yaml) is on, the container serves TLS, and a fixed http probe would report the
container unhealthy precisely because the operator turned encryption on.

Rather than reading the configuration — which lives on a volume this process may not be
able to open — it tries both. The certificate is deliberately NOT verified: it is the
container's own self-signed one by default, and this check asks "is the app alive", not
"is the certificate trusted".

The port is read from the server's own command line, because a command-line port wins over
IPMIDECK_SERVER_PORT and config.yaml: the image's CMD passes `--port 3000`, and under host
networking, where a port mapping does nothing, the way to move the port is to override that
CMD. Reading the variable alone would probe a port nothing listens on.
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.request
from pathlib import Path

DEFAULT_PORT = 3000  # the CMD in the Dockerfile
UNVERIFIED = ssl._create_unverified_context()


def port_from_argv(argv: list[str]) -> int | None:
    """The `--port N` / `--port=N` value of an ipmideck command line, or None."""
    if not any("ipmideck" in arg or "backend.main" in arg for arg in argv[:3]):
        return None
    for i, arg in enumerate(argv):
        value = None
        if arg == "--port" and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--port="):
            value = arg.split("=", 1)[1]
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def served_port() -> int:
    """The port the running server was given: its command line, else the variable, else 3000."""
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = cmdline.read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        port = port_from_argv(argv)
        if port is not None:
            return port
    try:
        return int(os.environ.get("IPMIDECK_SERVER_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def main() -> int:
    path = f"://localhost:{served_port()}/api/health"
    for scheme, context in (("http", None), ("https", UNVERIFIED)):
        try:
            with urllib.request.urlopen(scheme + path, context=context, timeout=4) as r:
                if r.status == 200:
                    return 0
        except Exception:
            continue
    return 1


if __name__ == "__main__":
    sys.exit(main())
