"""Container health probe: is the dashboard answering, over whichever scheme it came up on?

The probe cannot assume http. Once `IPMIDECK_SERVER_HTTPS` (or the `https` key in
config.yaml) is on, the container serves TLS, and a fixed http probe would report the
container unhealthy precisely because the operator turned encryption on.

Rather than reading the configuration — which lives on a volume this process may not be
able to open — it tries both. The certificate is deliberately NOT verified: it is the
container's own self-signed one by default, and this check asks "is the app alive", not
"is the certificate trusted".

The port is fixed at 3000 because the image's CMD passes `--port 3000`, and a command-line
port wins over IPMIDECK_SERVER_PORT and config.yaml. Reading that variable here would probe
a port nothing listens on.
"""

from __future__ import annotations

import ssl
import sys
import urllib.request

PORT = 3000  # matches the CMD in the Dockerfile
PATH = f"://localhost:{PORT}/api/health"
UNVERIFIED = ssl._create_unverified_context()


def main() -> int:
    for scheme, context in (("http", None), ("https", UNVERIFIED)):
        try:
            with urllib.request.urlopen(scheme + PATH, context=context, timeout=4) as r:
                if r.status == 200:
                    return 0
        except Exception:
            continue
    return 1


if __name__ == "__main__":
    sys.exit(main())
