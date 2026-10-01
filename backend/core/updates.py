"""Version history, install-method detection and published-version lookup.

Three properties this module has to keep, in priority order:

1. **The version history reads with no network at all.** The changelog is a file that ships
   inside the package, not something fetched at display time. An air-gapped install shows the
   same history as a connected one.
2. **No HTTP client outside the standard library.** Every outbound request here goes through
   ``urllib.request``. The runtime dependency list is a public, checkable claim: adding a
   requests/httpx-class package would falsify it.
3. **Nothing leaves the machine unless the operator asked for it.** This module never starts a
   request on its own — every fetch is called from a code path that has already established
   either an explicit operator action or a stored consent.

Importing this module performs no I/O.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path

from backend.core.branding import APP_NAME, VERSION

logger = logging.getLogger("ipmideck.updates")

# The packaged copy of the version history. It lives next to this package (not at the repository
# root) because only files inside the import package are guaranteed to land in the wheel; a copy
# outside it would be missing from every pip and Docker install, which is exactly the case that
# must keep working offline.
_CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# A version history is prose written by hand; anything past this size is a corrupt or hostile file
# rather than a changelog, and reading it whole would hand an attacker a memory-exhaustion lever.
_MAX_CHANGELOG_BYTES = 512 * 1024

# Bound on any response we read from the network, for the same reason: a remote endpoint we do not
# control must not be able to decide how much memory this process allocates.
_MAX_RESPONSE_BYTES = 256 * 1024

# Short by design. A version check is never worth stalling a request or a console keypress on, and
# on an air-gapped box the socket fails fast instead of hanging the caller.
DEFAULT_TIMEOUT = 6.0

# Sent verbatim on every outbound request. It carries the product name and the running version and
# nothing else — no install identifier, no hostname, no counter. The endpoint still sees the
# caller's IP address, as with any request.
USER_AGENT = f"{APP_NAME}/{VERSION}"

PYPI_URL = "https://pypi.org/simple/ipmideck/"
DOCKERHUB_URL = (
    "https://hub.docker.com/v2/repositories/devluigi06/ipmideck/tags"
    "?page_size=25&ordering=last_updated"
)
GITHUB_URL = "https://api.github.com/repos/ipmideck/IPMIDeck/releases/latest"
# One named release, by tag. Asked only after an index or registry lookup found a newer version,
# because those two channels carry no release notes and so cannot tell a security release apart.
GITHUB_TAG_URL = "https://api.github.com/repos/ipmideck/IPMIDeck/releases/tags/{tag}"
RELEASES_URL = "https://github.com/ipmideck/IPMIDeck/releases"
CHANGELOG_URL = "https://github.com/ipmideck/IPMIDeck/blob/main/CHANGELOG.md"


# --- install method ---------------------------------------------------------------------------

DOCKER = "docker"
PIP = "pip"
GIT = "git"
UNKNOWN = "unknown"

INSTALL_METHODS = (DOCKER, PIP, GIT, UNKNOWN)


# Values an application-container runtime puts in PID 1's ``container`` variable. LXC and
# systemd-nspawn set the same variable for a whole-system container, which boots its own init and
# gets this app by pip or a clone like any host does, so those values must not count.
_APP_CONTAINER_RUNTIMES = frozenset({b"docker", b"podman", b"oci"})


def _in_container() -> bool:
    """True when this process is running inside an application container built from an image.

    Several markers because no single one is reliable: Docker writes /.dockerenv and Podman
    writes /run/.containerenv, while other rootless runtimes write neither and instead set
    ``container=`` in PID 1's environment. That variable is only trusted for the runtimes in
    ``_APP_CONTAINER_RUNTIMES``; an LXC or systemd-nspawn system container sets it too, but is
    updated like a host, not by pulling a new image. Reading /proc/1/environ can fail (non-Linux,
    restricted /proc), which is not an error — it just means that marker is unavailable.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        with open("/proc/1/environ", "rb") as fh:
            environ = fh.read(4096)
    except OSError:
        return False
    for entry in environ.split(b"\0"):
        key, _, value = entry.partition(b"=")
        if key == b"container":
            return value in _APP_CONTAINER_RUNTIMES
    return False


def detect_install_method() -> str:
    """Resolve how this instance was installed, which decides where its updates come from.

    Order matters, and it is not the order the markers suggest.

    The container check comes first because an image is built by installing the package, so the
    distribution metadata is present inside it too — checking that first would report every
    Docker install as a Python-index install and point it at the wrong source.

    The working-tree check comes before the distribution check for the same class of reason: a
    checkout that has also been installed in editable mode carries distribution metadata, but it
    is updated with a pull, not by reinstalling from the index. The tree it sits in is the
    stronger signal about how a new version actually arrives. A container image never carries a
    working tree (the build context excludes it), so the two cases cannot collide.
    """
    if _in_container():
        return DOCKER
    if (Path(__file__).resolve().parent.parent.parent / ".git").exists():
        return GIT
    try:
        _dist_version("ipmideck")
    except PackageNotFoundError:
        return UNKNOWN
    return PIP


# --- version comparison -----------------------------------------------------------------------

# MAJOR.MINOR.PATCH with an optional pre-release suffix. Deliberately strict: a moving tag such as
# `latest` or `2.0`, or a commit tag such as `sha-eb8452f`, carries no ordering information, and
# guessing one would let a rolling tag masquerade as a release.
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?([0-9A-Za-z.\-]+))?$")


def parse_version(raw: str | None) -> tuple | None:
    """Parse a strict semantic version into a comparable tuple, or None if it is not one.

    The fourth element orders pre-releases below the matching final release: a final release gets
    a sentinel that sorts after any suffix, so 2.1.0 > 2.1.0-rc1 without special-casing callers.
    """
    if not raw or not isinstance(raw, str):
        return None
    match = _VERSION_RE.match(raw.strip())
    if not match:
        return None
    major, minor, patch, suffix = match.groups()
    # (0, suffix) for a pre-release, (1, "") for a final release — tuples compare element-wise, so
    # the leading flag alone decides the ordering between the two.
    tail = (0, suffix.lower()) if suffix else (1, "")
    return (int(major), int(minor), int(patch), tail)


def _is_prerelease(parsed: tuple) -> bool:
    """True for a parsed version that carries a pre-release suffix (see ``parse_version``)."""
    return parsed[3][0] == 0


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True only when both sides parse and candidate is strictly greater.

    Unparseable input on either side returns False. Announcing an update on the strength of a
    version string nobody could order would be worse than staying quiet.
    """
    left = parse_version(candidate)
    right = parse_version(current)
    if left is None or right is None:
        return False
    return left > right


# --- changelog --------------------------------------------------------------------------------


@dataclass
class ChangelogEntry:
    """One released (or unreleased) section of the version history."""

    version: str
    date: str | None = None
    is_security: bool = False
    is_unreleased: bool = False
    body: str = ""

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "date": self.date,
            "is_security": self.is_security,
            "is_unreleased": self.is_unreleased,
            "body": self.body,
        }


_HEADING_RE = re.compile(r"^##\s+\[([^\]]+)\](?:\s*-\s*(\d{4}-\d{2}-\d{2}))?\s*$")
# The "### Security" grouping is what marks a release as a security release. It is the same
# grouping the release workflow relies on, so one convention drives both the release body and the
# badge shown in the interface.
_SECURITY_RE = re.compile(r"^###\s+Security\s*$", re.MULTILINE)
# Reference-link definitions at the foot of the file ("[2.0.1]: https://…"). They belong to the
# markdown source, not to any release's prose.
_LINK_DEF_RE = re.compile(r"^\[[^\]]+\]:\s+\S+\s*$")


def read_changelog_text(path: Path | None = None) -> str:
    """Return the packaged version history as text, or "" when it is unreadable.

    A missing or oversized file degrades to an empty history rather than raising: the interface
    has an empty state, and a broken read here must not take down the page that shows it.
    """
    target = path or _CHANGELOG_PATH
    try:
        if target.stat().st_size > _MAX_CHANGELOG_BYTES:
            logger.warning("Version history at %s is larger than expected — not read", target)
            return ""
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read the packaged version history: %s", exc)
        return ""


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """Split the version history into entries, newest first (source order is preserved).

    Everything before the first version heading is the file's own preamble and is dropped; so are
    the trailing reference-link definitions. Each entry keeps its raw body so the interface can
    render the groups and bullets the file already uses without a markdown dependency.
    """
    entries: list[ChangelogEntry] = []
    current: ChangelogEntry | None = None
    body_lines: list[str] = []

    def flush() -> None:
        if current is None:
            return
        current.body = "\n".join(body_lines).strip()
        current.is_security = bool(_SECURITY_RE.search(current.body))
        entries.append(current)

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            raw_version, date = heading.groups()
            current = ChangelogEntry(
                version=raw_version.strip(),
                date=date,
                is_unreleased=raw_version.strip().lower() == "unreleased",
            )
            body_lines = []
            continue
        if current is not None and not _LINK_DEF_RE.match(line):
            body_lines.append(line)

    flush()
    return entries


# --- published version lookup -------------------------------------------------------------------

# The only hosts a lookup may reach, redirects included.
_ALLOWED_HOSTS = frozenset({"pypi.org", "hub.docker.com", "api.github.com"})


def safe_release_url(candidate) -> str:
    """A release link from an endpoint's answer, or the releases page if it is anything else.

    The link is stored and rendered as an anchor, so only a page of this project's releases is
    accepted; a ``javascript:`` or foreign URL in a response never reaches the interface.
    """
    if isinstance(candidate, str) and candidate.startswith(RELEASES_URL + "/"):
        return candidate
    return RELEASES_URL


def _is_security_body(body) -> bool:
    """A release body marks a security release only through its ``### Security`` grouping.

    That is the rule the version history uses and the heading the release workflow writes. A
    phrase found in the prose would mark "this is not a security release" as one.
    """
    return isinstance(body, str) and bool(_SECURITY_RE.search(body))


@dataclass
class UpdateProbe:
    """The outcome of one lookup. ``error`` set means nothing else on it is meaningful."""

    source: str
    latest_version: str | None = None
    release_url: str | None = None
    is_security: bool = False
    # A newer version was found but its release notes could not be read, so whether it is a
    # security release is unknown, which is not the same as known to be an ordinary one.
    security_unresolved: bool = False
    error: str | None = None
    checked_at: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "latest_version": self.latest_version,
            "release_url": self.release_url,
            "is_security": self.is_security,
            "security_unresolved": self.security_unresolved,
            "error": self.error,
            "checked_at": self.checked_at,
        }


def _check_target(url: str) -> None:
    target = urllib.parse.urlsplit(url)
    if target.scheme != "https" or target.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"refusing to contact {url}")


class _UpdateEndpointRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https on one of the update endpoints, and log it like a request.

    The default handler follows up to ten redirects to http, https or ftp, which would let a
    redirecting endpoint move the request, version string included, to a cleartext host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_target(newurl)
        logger.info("Update check: following a redirect to %s", newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_UpdateEndpointRedirects)


def _urlopen(request: urllib.request.Request, timeout: float):
    """The single place a socket is opened. Tests replace it to forbid or fake the network."""
    return _OPENER.open(request, timeout=timeout)


def _fetch(url: str, accept: str, timeout: float) -> dict:
    """GET a JSON document with the standard library only.

    Logged verbatim before the socket opens so an operator auditing their own logs can see every
    address this process contacts, without having to run a packet capture to trust the claim.
    """
    _check_target(url)
    logger.info("Update check: requesting %s", url)
    request = urllib.request.Request(  # noqa: S310 — https on an allow-listed host, checked above
        url,
        headers={"Accept": accept, "User-Agent": USER_AGENT},
        method="GET",
    )
    with _urlopen(request, timeout) as response:
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("response larger than expected")
    data = json.loads(raw.decode("utf-8"))
    # Every endpoint asked here answers with an object. Anything else is a broken or hostile
    # answer, and refusing it once here spares each channel from guarding against it.
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def _newest(versions, include_prereleases: bool = False) -> str | None:
    """Highest strictly-semantic version in an iterable; anything unparseable is discarded.

    Pre-releases are discarded too unless asked for: an install running a final release must not
    be told to move to a release candidate just because the index already lists one.
    """
    parsed = [(parse_version(v), v) for v in versions]
    ranked = [
        (key, raw)
        for key, raw in parsed
        if key is not None and (include_prereleases or not _is_prerelease(key))
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[-1][1]


def _running_prerelease() -> bool:
    """True when this build is itself a pre-release, so its operator has already opted into them."""
    running = parse_version(VERSION)
    return running is not None and _is_prerelease(running)


def _latest_from_pypi(timeout: float) -> UpdateProbe:
    """The index API returns the file list; the simple JSON form is an order of magnitude
    smaller than the project JSON route for the same answer."""
    data = _fetch(timeout=timeout, url=PYPI_URL, accept="application/vnd.pypi.simple.v1+json")
    versions = data.get("versions")
    latest = _newest(
        versions if isinstance(versions, list) else [],
        include_prereleases=_running_prerelease(),
    )
    return UpdateProbe(source=PIP, latest_version=latest, release_url=RELEASES_URL)


def _latest_from_dockerhub(timeout: float) -> UpdateProbe:
    """Tags come back newest-first, but the newest is usually a moving tag (`latest`, `2.0`) or a
    commit tag (`sha-…`). Only strictly semantic tags are ordered; the rest are discarded."""
    data = _fetch(timeout=timeout, url=DOCKERHUB_URL, accept="application/json")
    results = data.get("results")
    entries = results if isinstance(results, list) else []
    names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    latest = _newest(names, include_prereleases=_running_prerelease())
    return UpdateProbe(source=DOCKER, latest_version=latest, release_url=RELEASES_URL)


def _latest_from_github(timeout: float) -> UpdateProbe:
    """The releases endpoint carries the release body as well as the tag, which is the only
    channel that can tell a security release from an ordinary one."""
    data = _fetch(timeout=timeout, url=GITHUB_URL, accept="application/vnd.github+json")
    tag = data.get("tag_name")
    return UpdateProbe(
        source=GIT,
        latest_version=tag if isinstance(tag, str) and tag else None,
        release_url=safe_release_url(data.get("html_url")),
        is_security=_is_security_body(data.get("body")),
    )


def _mark_security_from_release(probe: UpdateProbe, timeout: float) -> None:
    """Ask the published release of a newer version found on the index or registry whether it
    is a security release. Those two channels carry no release notes of their own.

    Best effort: a failed lookup keeps the found version and leaves ``error`` unset, because a
    missing badge is better than turning a found update into an error. It does record that the
    answer is unknown. The release workflow publishes to the index and the registry first and
    leaves the GitHub release as a draft until it is published by hand, and anonymous callers get
    a 404 for a draft, so this window is ordinary rather than exceptional.
    """
    tag = "v" + probe.latest_version.lstrip("v")
    url = GITHUB_TAG_URL.format(tag=urllib.parse.quote(tag, safe=""))
    try:
        data = _fetch(timeout=timeout, url=url, accept="application/vnd.github+json")
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.debug("Could not read the release notes of %s: %s", tag, exc)
        probe.security_unresolved = True
        return
    if not isinstance(data, dict):
        probe.security_unresolved = True
        return
    probe.security_unresolved = False
    probe.is_security = _is_security_body(data.get("body"))
    probe.release_url = safe_release_url(data.get("html_url"))


_CHANNELS = {
    PIP: _latest_from_pypi,
    DOCKER: _latest_from_dockerhub,
    GIT: _latest_from_github,
    # A source tree that is neither a container, an installed distribution nor a checkout still
    # has a meaningful answer: the published releases.
    UNKNOWN: _latest_from_github,
}


def fetch_latest(method: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> UpdateProbe:
    """Look up the newest published version for this install's channel.

    Never raises. Every failure — no route to host, DNS failure, rate limit, malformed payload —
    comes back as ``error`` on the probe, because the failure modes here are ordinary on an
    air-gapped or firewalled box and must not produce recurring tracebacks in an operator's log.
    """
    channel = method or detect_install_method()
    fetcher = _CHANNELS.get(channel, _latest_from_github)
    try:
        probe = fetcher(timeout)
    except urllib.error.HTTPError as exc:
        # 403 from the releases API is nearly always the anonymous hourly budget, which is a
        # different situation for the operator than the endpoint being broken.
        reason = "rate_limited" if exc.code in (403, 429) else f"http_{exc.code}"
        return UpdateProbe(source=channel, error=reason)
    except (urllib.error.URLError, socket.timeout, TimeoutError, http.client.HTTPException):
        # A body cut short (IncompleteRead) is raised while reading the response, where urllib no
        # longer wraps errors, and it is an HTTPException rather than an OSError.
        return UpdateProbe(source=channel, error="unreachable")
    except (ValueError, OSError) as exc:
        logger.debug("Update check failed: %s", exc)
        return UpdateProbe(source=channel, error="invalid_response")
    except Exception as exc:  # noqa: BLE001 — see docstring: a lookup must never raise
        logger.debug("Update check failed unexpectedly: %r", exc)
        return UpdateProbe(source=channel, error="invalid_response")
    if probe.latest_version is None:
        probe.error = "no_release_found"
    elif probe.source in (PIP, DOCKER) and is_newer(probe.latest_version, VERSION):
        _mark_security_from_release(probe, timeout)
    return probe


def env_flag(name: str, default: bool) -> bool:
    """Read a boolean environment override using the repo's existing truthy spellings."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes")
