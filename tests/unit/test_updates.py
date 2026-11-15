"""Update-lookup core: version ordering, install-method detection, and the channel fetchers."""

from __future__ import annotations

import http.client
import json
import pathlib
import ssl
import threading
import time
import tomllib
import urllib.error
import urllib.request

import pytest

from backend.core import updates

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RELEASE_PAGE = updates.RELEASES_URL + "/tag/v2.0.2"


# --- the public no-HTTP-client claim ------------------------------------------------------------

# Anything in this set would make "there is no HTTP client in the runtime dependencies" false.
# The claim is checkable from package metadata by anyone, so it is checked here too.
_HTTP_CLIENTS = {"requests", "httpx", "aiohttp", "urllib3", "httpcore", "requests-toolbelt", "h11"}


def test_runtime_dependencies_carry_no_http_client():
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    names = {d.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower() for d in deps}
    assert not (names & _HTTP_CLIENTS), f"an HTTP client entered the runtime deps: {names & _HTTP_CLIENTS}"


def test_the_update_module_uses_only_the_standard_library_client():
    source = (REPO_ROOT / "backend" / "core" / "updates.py").read_text(encoding="utf-8")
    for banned in _HTTP_CLIENTS:
        assert f"import {banned}" not in source


# --- version ordering ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["latest", "2.0", "sha-eb8452f", "", None, "v2", "two.oh.oh"])
def test_non_semantic_tags_are_discarded(raw):
    assert updates.parse_version(raw) is None


@pytest.mark.parametrize(
    "raw,expected_head",
    [("2.0.1", (2, 0, 1)), ("v2.1.0", (2, 1, 0)), ("2.1.0-rc1", (2, 1, 0))],
)
def test_semantic_tags_parse(raw, expected_head):
    assert updates.parse_version(raw)[:3] == expected_head


def test_a_prerelease_sorts_below_its_final_release():
    assert updates.parse_version("2.1.0") > updates.parse_version("2.1.0-rc1")


# Each pair is (lower, higher) in PEP 440 order.
@pytest.mark.parametrize(
    "lower, higher",
    [
        ("2.1.0.dev1", "2.1.0a1"),
        ("2.1.0a2", "2.1.0b1"),
        ("2.1.0alpha3", "2.1.0beta1"),
        ("2.1.0b9", "2.1.0rc1"),
        ("2.1.0c1", "2.1.0rc2"),
        ("2.1.0rc9", "2.1.0rc10"),
        ("2.1.0-rc.9", "2.1.0-rc.10"),
        ("2.1.0rc10", "2.1.0"),
        ("2.1.0.dev99", "2.1.0"),
        # A suffix of no known kind cannot be placed, so it ranks below everything.
        ("2.1.0-nightly", "2.1.0.dev1"),
        ("2.1.0-nightly", "2.1.0"),
        # A post-release is a final release, ordered after the one it follows.
        ("2.0.2", "2.0.2.post1"),
        ("2.0.2.post1", "2.0.2.post2"),
        ("2.0.2.post9", "2.0.3.dev1"),
    ],
)
def test_release_phases_follow_pep_440_order(lower, higher):
    assert updates.parse_version(lower) < updates.parse_version(higher)
    assert updates.is_newer(higher, lower) is True
    assert updates.is_newer(lower, higher) is False


def test_a_post_release_is_a_final_release():
    """It is offered to an install running a final release like any other release."""
    assert updates._is_prerelease(updates.parse_version("2.0.2.post1")) is False
    assert updates._newest(["2.0.2", "2.0.2.post1"]) == "2.0.2.post1"


@pytest.mark.parametrize("raw", ["2.1.0.dev1", "2.1.0a1", "2.1.0-beta", "2.1.0rc1", "2.1.0-x"])
def test_every_other_suffix_is_a_prerelease(raw):
    assert updates._is_prerelease(updates.parse_version(raw)) is True


# --- hostile version strings --------------------------------------------------------------------

# Every version string comes from a remote answer: a tag name, an index entry. A run of digits
# that cannot match makes a pattern with a digit-or-suffix ambiguity try every split of it.
_HOSTILE_VERSION = "1.1." + "1" * 20_000 + "!"


def _parse_timed(raw):
    started = time.perf_counter()
    parsed = updates.parse_version(raw)
    return parsed, time.perf_counter() - started


def test_a_hostile_version_string_is_refused_quickly():
    parsed, elapsed = _parse_timed(_HOSTILE_VERSION)
    assert parsed is None
    assert elapsed < 0.5, f"parsing one version took {elapsed:.2f}s"


def test_the_pattern_alone_stays_linear_on_hostile_input(monkeypatch):
    """With the length limit out of the way, the pattern itself must still fail fast."""
    monkeypatch.setattr(updates, "_MAX_VERSION_LENGTH", 10**6)
    parsed, elapsed = _parse_timed(_HOSTILE_VERSION)
    assert parsed is None
    assert elapsed < 0.5, f"parsing one version took {elapsed:.2f}s"


@pytest.mark.parametrize("lift_length_limit", [False, True])
def test_a_huge_number_is_refused_rather_than_raised(monkeypatch, lift_length_limit):
    """int() refuses more than a few thousand digits with a ValueError of its own."""
    if lift_length_limit:
        monkeypatch.setattr(updates, "_MAX_VERSION_LENGTH", 10**6)
    assert updates.parse_version("1.1." + "1" * 5000) is None


def test_a_ten_digit_number_is_refused_not_split_into_number_and_suffix():
    """Nine digits is the bound, and the digit after it must not be read as a pre-release tag."""
    assert updates.parse_version("2.0.1234567890") is None
    assert updates.parse_version("2.0.123456789")[:3] == (2, 0, 123456789)


def test_a_version_longer_than_the_limit_is_refused():
    longest = "2.0.0-" + "a" * (updates._MAX_VERSION_LENGTH - len("2.0.0-"))
    assert updates.parse_version(longest) is not None
    assert updates.parse_version(longest + "a") is None


@pytest.mark.parametrize("raw", [5, 2.0, ["2.0.1"], {"v": "2.0.1"}, True, b"2.0.1"])
def test_a_version_of_the_wrong_type_is_refused(raw):
    assert updates.parse_version(raw) is None


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("2.0.2", "2.0.1", True),
        ("2.0.1", "2.0.1", False),
        ("2.0.0", "2.0.1", False),
        ("3.0.0", "2.9.9", True),
        ("latest", "2.0.1", False),
        ("2.0.2", "latest", False),
    ],
)
def test_is_newer(candidate, current, expected):
    assert updates.is_newer(candidate, current) is expected


def test_newest_ignores_moving_and_commit_tags():
    assert updates._newest(["latest", "2.0", "sha-abc", "2.0.0", "2.0.1"]) == "2.0.1"


def test_newest_of_nothing_orderable_is_none():
    assert updates._newest(["latest", "2.0", "sha-abc"]) is None


def test_newest_skips_prereleases_unless_asked_for():
    assert updates._newest(["2.0.1", "2.1.0a1"]) == "2.0.1"
    assert updates._newest(["2.0.1", "2.1.0a1"], include_prereleases=True) == "2.1.0a1"


# --- install method -----------------------------------------------------------------------------


def test_container_marker_wins_over_the_installed_distribution(monkeypatch):
    """A container image is built by installing the package, so the distribution metadata is
    present there too — the container answer has to come first or Docker installs get pointed at
    the Python index."""
    monkeypatch.setattr(updates, "_in_container", lambda: True)
    assert updates.detect_install_method() == updates.DOCKER


def test_installed_distribution_is_reported_as_pip(monkeypatch, tmp_path):
    """A plain install has no working tree above the package."""
    monkeypatch.setattr(updates, "_in_container", lambda: False)
    monkeypatch.setattr(updates, "_dist_version", lambda name: "2.0.1")
    monkeypatch.setattr(updates, "__file__", str(tmp_path / "core" / "updates.py"))
    assert updates.detect_install_method() == updates.PIP


def test_a_checkout_is_reported_as_a_clone(monkeypatch):
    """This test suite runs from a working tree, which is exactly the case being asserted: an
    editable install still carries distribution metadata, but it is updated with a pull."""
    monkeypatch.setattr(updates, "_in_container", lambda: False)
    assert updates.detect_install_method() == updates.GIT


def test_neither_a_tree_nor_a_distribution_is_left_unknown(monkeypatch, tmp_path):
    from importlib.metadata import PackageNotFoundError

    def _absent(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(updates, "_in_container", lambda: False)
    monkeypatch.setattr(updates, "_dist_version", _absent)
    monkeypatch.setattr(updates, "__file__", str(tmp_path / "core" / "updates.py"))
    assert updates.detect_install_method() == updates.UNKNOWN


def _fake_pid1_environ(monkeypatch, tmp_path, content: bytes) -> None:
    environ = tmp_path / "environ"
    environ.write_bytes(content)
    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/1/environ":
            return real_open(environ, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)


@pytest.mark.parametrize("runtime", [b"podman", b"docker", b"oci"])
def test_container_env_marker_is_read(monkeypatch, tmp_path, runtime):
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00container=" + runtime + b"\x00")
    monkeypatch.setattr(updates.Path, "exists", lambda self: False)
    assert updates._in_container() is True


@pytest.mark.parametrize("runtime", [b"lxc", b"systemd-nspawn", b"lxc-libvirt"])
def test_a_system_container_is_not_reported_as_docker(monkeypatch, tmp_path, runtime):
    """LXC and systemd-nspawn set the same variable for a whole-system container. The app inside
    one is installed with pip or a clone and updated like a host, so pointing it at the image
    registry would send the operator to the wrong place."""
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00container=" + runtime + b"\x00")
    monkeypatch.setattr(updates.Path, "exists", lambda self: False)
    assert updates._in_container() is False


def test_only_the_exact_container_variable_counts(monkeypatch, tmp_path):
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00my_container=docker\x00")
    monkeypatch.setattr(updates.Path, "exists", lambda self: False)
    assert updates._in_container() is False


def test_the_podman_marker_file_is_read(monkeypatch, tmp_path):
    """Podman writes /run/.containerenv rather than /.dockerenv."""
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00")
    monkeypatch.setattr(
        updates.Path, "exists", lambda self: self.as_posix() == "/run/.containerenv"
    )
    assert updates._in_container() is True


def test_the_docker_marker_file_alone_is_enough(monkeypatch, tmp_path):
    """Docker writes /.dockerenv and sets no container variable, and the image carries the
    installed distribution, so this one file is what keeps the answer off the Python index."""
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00")
    monkeypatch.setattr(updates.Path, "exists", lambda self: self.as_posix() == "/.dockerenv")
    monkeypatch.setattr(updates, "_dist_version", lambda name: "2.0.1")
    assert updates._in_container() is True
    assert updates.detect_install_method() == updates.DOCKER


def _refused_for(name):
    """Path.exists as it behaves when the host denies the stat of one path: it raises."""

    def exists(self):
        if self.as_posix() == name or self.name == name:
            raise PermissionError(13, "Permission denied", str(self))
        return False

    return exists


def test_a_marker_the_host_refuses_to_show_counts_as_absent(monkeypatch, tmp_path):
    """A hardened host can deny the stat of /run outright; detection falls through instead."""
    _fake_pid1_environ(monkeypatch, tmp_path, b"PATH=/usr/bin\x00")
    monkeypatch.setattr(updates.Path, "exists", _refused_for("/run/.containerenv"))
    assert updates._in_container() is False


def test_a_refused_working_tree_probe_falls_through_to_the_distribution(monkeypatch):
    monkeypatch.setattr(updates, "_in_container", lambda: False)
    monkeypatch.setattr(updates.Path, "exists", _refused_for(".git"))
    monkeypatch.setattr(updates, "_dist_version", lambda name: "2.0.1")
    assert updates.detect_install_method() == updates.PIP


def test_metadata_too_broken_to_read_is_no_distribution(monkeypatch, tmp_path):
    def broken(name):
        raise KeyError("Version")

    monkeypatch.setattr(updates, "_in_container", lambda: False)
    monkeypatch.setattr(updates, "_dist_version", broken)
    monkeypatch.setattr(updates, "__file__", str(tmp_path / "core" / "updates.py"))
    assert updates.detect_install_method() == updates.UNKNOWN


def test_a_failed_install_detection_is_a_reason_not_an_exception(monkeypatch):
    """The lookup promises never to raise, and choosing its channel is part of the lookup."""

    def broken():
        raise RuntimeError("detection failed")

    opened = []
    monkeypatch.setattr(updates, "detect_install_method", broken)
    monkeypatch.setattr(updates, "_urlopen", lambda request, timeout: opened.append(request))
    probe = updates.fetch_latest()
    assert probe.error == "invalid_response"
    assert probe.source == updates.UNKNOWN
    assert opened == []


# --- changelog parsing --------------------------------------------------------------------------

SAMPLE = """# Changelog

Preamble that belongs to nobody.

## [Unreleased]

### Security

- Fixed something serious.

## [2.0.1] - 2026-07-25

### Fixed

- An ordinary fix.

## [2.0.0] - 2026-07-13

First release.

[Unreleased]: https://example.invalid/compare
[2.0.1]: https://example.invalid/2.0.1
"""


def test_entries_are_split_in_source_order():
    entries = updates.parse_changelog(SAMPLE)
    assert [e.version for e in entries] == ["Unreleased", "2.0.1", "2.0.0"]


def test_dates_are_captured_when_present():
    entries = {e.version: e for e in updates.parse_changelog(SAMPLE)}
    assert entries["2.0.1"].date == "2026-07-25"
    assert entries["Unreleased"].date is None


def test_a_security_grouping_marks_the_entry():
    entries = {e.version: e for e in updates.parse_changelog(SAMPLE)}
    assert entries["Unreleased"].is_security is True
    assert entries["2.0.1"].is_security is False


def test_the_unreleased_section_is_flagged():
    entries = {e.version: e for e in updates.parse_changelog(SAMPLE)}
    assert entries["Unreleased"].is_unreleased is True
    assert entries["2.0.0"].is_unreleased is False


def test_the_preamble_and_link_definitions_are_dropped():
    bodies = "\n".join(e.body for e in updates.parse_changelog(SAMPLE))
    assert "belongs to nobody" not in bodies
    assert "example.invalid" not in bodies


def test_empty_input_yields_no_entries():
    assert updates.parse_changelog("") == []


# --- channel fetchers ---------------------------------------------------------------------------


def _stub_fetch(monkeypatch, payload):
    calls = []

    def fake(url, accept, timeout, cancel=None):
        calls.append(url)
        return payload

    monkeypatch.setattr(updates, "_fetch", fake)
    return calls


class _FakeResponse:
    """A response with a fixed body that records every size it was asked to read."""

    def __init__(self, body: bytes):
        self.body = body
        self.requested = []

    def read(self, n=-1):
        self.requested.append(n)
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, body: bytes) -> _FakeResponse:
    response = _FakeResponse(body)
    monkeypatch.setattr(updates, "_urlopen", lambda *a, **k: response)
    return response


def test_the_python_index_channel_picks_the_highest_release(monkeypatch):
    _stub_fetch(monkeypatch, {"versions": ["2.0.0", "2.0.1", "1.9.9"]})
    probe = updates.fetch_latest(updates.PIP)
    assert probe.latest_version == "2.0.1"
    assert probe.error is None


def test_the_registry_channel_discards_moving_tags(monkeypatch):
    _stub_fetch(
        monkeypatch,
        {"results": [{"name": "latest"}, {"name": "2.0"}, {"name": "sha-abc"}, {"name": "2.0.1"}]},
    )
    probe = updates.fetch_latest(updates.DOCKER)
    assert probe.latest_version == "2.0.1"


def test_the_release_channel_reports_a_security_release(monkeypatch):
    _stub_fetch(
        monkeypatch,
        {"tag_name": "v2.0.2", "body": "### Security\n\n- Fixed a traversal.", "html_url": RELEASE_PAGE},
    )
    probe = updates.fetch_latest(updates.GIT)
    assert probe.latest_version == "v2.0.2"
    assert probe.is_security is True
    assert probe.release_url == RELEASE_PAGE


def test_an_ordinary_release_is_not_marked_as_security(monkeypatch):
    _stub_fetch(monkeypatch, {"tag_name": "v2.1.0", "body": "### Added\n\n- A feature."})
    assert updates.fetch_latest(updates.GIT).is_security is False


def test_the_release_notes_come_with_the_answer(monkeypatch):
    _stub_fetch(monkeypatch, {"tag_name": "v2.1.0", "body": "### Added\n\n- A feature."})
    assert updates.fetch_latest(updates.GIT).notes == "### Added\n\n- A feature."


@pytest.mark.parametrize("body", [None, "", "   ", 42, ["### Added"]])
def test_a_release_without_readable_notes_has_none(body):
    assert updates.release_notes(body) is None


def test_overlong_release_notes_are_cut_rather_than_passed_on():
    notes = updates.release_notes("x" * (updates._MAX_NOTES + 100))
    assert notes is not None and len(notes) == updates._MAX_NOTES


def test_security_in_the_prose_does_not_mark_the_release(monkeypatch):
    """Only the heading counts, the same rule the version history uses."""
    _stub_fetch(monkeypatch, {"tag_name": "v2.1.0", "body": "This is not a security release."})
    assert updates.fetch_latest(updates.GIT).is_security is False


def test_a_security_grouping_with_windows_line_endings_still_counts(monkeypatch):
    _stub_fetch(monkeypatch, {"tag_name": "v2.1.0", "body": "### Security\r\n\r\n- Fixed."})
    assert updates.fetch_latest(updates.GIT).is_security is True


def test_an_empty_channel_answer_is_reported_rather_than_guessed(monkeypatch):
    _stub_fetch(monkeypatch, {"versions": []})
    probe = updates.fetch_latest(updates.PIP)
    assert probe.latest_version is None
    assert probe.error == "no_release_found"


@pytest.mark.parametrize("channel", [updates.PIP, updates.DOCKER, updates.GIT])
@pytest.mark.parametrize("body", [b"[]", b'["99.0.0"]', b'"99.0.0"', b"null", b"5"])
def test_an_answer_that_is_not_an_object_is_a_reason(monkeypatch, channel, body):
    """A captive portal or a misbehaving proxy can answer 200 with anything at all."""
    _serve(monkeypatch, body)
    probe = updates.fetch_latest(channel)
    assert probe.error == "invalid_response"
    assert probe.latest_version is None


@pytest.mark.parametrize("body", [b"[]", b'"99.0.0"', b"null"])
def test_the_fetch_itself_refuses_an_answer_that_is_not_an_object(monkeypatch, body):
    """Refused where it is read, so no channel ever sees a payload it would have to guard."""
    _serve(monkeypatch, body)
    with pytest.raises(ValueError):
        updates._fetch(updates.PYPI_URL, "application/json", 1.0)


@pytest.mark.parametrize(
    "channel, payload",
    [
        (updates.PIP, {"versions": 5}),
        (updates.PIP, {"versions": {"99.0.0": {}}}),
        (updates.DOCKER, {"versions": 5}),
        (updates.DOCKER, {"results": 5}),
        (updates.DOCKER, {"results": ["99.0.0", 5]}),
        (updates.GIT, {"versions": 5}),
        (updates.GIT, {"tag_name": 5}),
        (updates.GIT, {"tag_name": ["v99.0.0"]}),
    ],
)
def test_a_field_of_the_wrong_type_is_treated_as_absent(monkeypatch, channel, payload):
    _serve(monkeypatch, json.dumps(payload).encode())
    probe = updates.fetch_latest(channel)
    assert probe.error == "no_release_found"
    assert probe.latest_version is None


def test_a_deeply_nested_answer_is_a_reason_not_an_exception(monkeypatch):
    """The JSON decoder gives up on deep nesting with a RecursionError, which is neither a
    ValueError nor an OSError, and a body well inside the size bound can carry it."""
    _serve(monkeypatch, b"[" * 100_000)
    assert updates.fetch_latest(updates.PIP).error == "invalid_response"


@pytest.mark.parametrize(
    "raised,expected",
    [
        (urllib.error.HTTPError("u", 403, "rate", {}, None), "rate_limited"),
        (urllib.error.HTTPError("u", 429, "rate", {}, None), "rate_limited"),
        (urllib.error.HTTPError("u", 500, "boom", {}, None), "http_500"),
        (urllib.error.URLError("no route to host"), "unreachable"),
        (TimeoutError(), "unreachable"),
        # Raised while reading the body, where urllib no longer wraps errors, and not an OSError.
        (http.client.IncompleteRead(b'{"vers'), "unreachable"),
        (ValueError("garbage"), "invalid_response"),
        (AttributeError("a shape nobody anticipated"), "invalid_response"),
    ],
)
def test_every_failure_comes_back_as_a_reason_not_an_exception(monkeypatch, raised, expected):
    """An air-gapped or firewalled instance is an ordinary state, not an incident: it must not
    produce recurring tracebacks in the operator's log."""

    def boom(url, accept, timeout, cancel=None):
        raise raised

    monkeypatch.setattr(updates, "_fetch", boom)
    probe = updates.fetch_latest(updates.PIP)
    assert probe.error == expected
    assert probe.latest_version is None


class _DroppedResponse:
    """A response whose connection fails while its body is being read."""

    def __init__(self, error: BaseException):
        self.error = error

    def read(self, n=-1):
        raise self.error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize(
    "dropped",
    [
        ConnectionResetError(104, "Connection reset by peer"),
        ConnectionAbortedError(103, "Software caused connection abort"),
        ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
        ssl.SSLError(1, "record layer failure"),
    ],
    ids=["reset", "aborted", "tls-eof", "tls-error"],
)
def test_a_connection_lost_while_reading_the_body_is_unreachable(monkeypatch, dropped):
    """urllib wraps failures while connecting, not while reading, so these arrive bare. They
    say the network failed, not that the endpoint answered with something malformed."""
    monkeypatch.setattr(updates, "_urlopen", lambda *a, **k: _DroppedResponse(dropped))
    probe = updates.fetch_latest(updates.PIP)
    assert probe.error == "unreachable"
    assert probe.latest_version is None


@pytest.mark.parametrize("body", [b'{"versions": ["2.0', b"\xff\xfe\x00", b"<html>portal</html>"])
def test_a_malformed_body_is_still_an_invalid_response(monkeypatch, body):
    _serve(monkeypatch, body)
    assert updates.fetch_latest(updates.PIP).error == "invalid_response"


def test_an_oversized_response_is_refused(monkeypatch):
    """A valid object followed by whitespace past the bound: any prefix a read could stop at,
    including the bound itself and one byte more, still parses as valid JSON. So only the size
    check can refuse it, and only a read of exactly one byte past the bound can feed that check
    without spending the memory the bound exists to protect."""
    head = b'{"versions": ["0.0.1"]}'
    body = head + b" " * (updates._MAX_RESPONSE_BYTES + 1024 - len(head))
    for bound in (updates._MAX_RESPONSE_BYTES, updates._MAX_RESPONSE_BYTES + 1, len(body)):
        assert json.loads(body[:bound])["versions"] == ["0.0.1"]
    response = _serve(monkeypatch, body)
    assert updates.fetch_latest(updates.PIP).error == "invalid_response"
    assert response.requested == [updates._MAX_RESPONSE_BYTES + 1]


def test_the_request_carries_no_install_identifier(monkeypatch):
    captured = {}

    class FakeResponse:
        def read(self, n=-1):
            return json.dumps({"versions": ["2.0.1"]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr(updates, "_urlopen", fake_urlopen)
    updates.fetch_latest(updates.PIP)
    agent = captured["headers"]["User-agent"]
    assert agent == f"IPMIDeck/{updates.VERSION}"
    # No cookie, no token, nothing that separates one install of this version from another.
    assert set(captured["headers"]) == {"Accept", "User-agent"}


def test_the_outbound_address_is_logged_before_the_socket_opens(monkeypatch, caplog):
    monkeypatch.setattr(updates, "_urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    with caplog.at_level("INFO", logger="ipmideck.updates"):
        updates.fetch_latest(updates.PIP)
    assert any(updates.PYPI_URL in r.getMessage() for r in caplog.records)


# --- security marker for the index and registry channels ----------------------------------------


def _stub_channels(monkeypatch, channel_payload, release_payload=None, release_error=None):
    calls = []

    def fake(url, accept, timeout, cancel=None):
        calls.append(url)
        if "/releases/tags/" in url:
            if release_error is not None:
                raise release_error
            return release_payload
        return channel_payload

    monkeypatch.setattr(updates, "_fetch", fake)
    return calls


_PIP_NEWER = {"versions": ["99.0.0"]}
_DOCKER_NEWER = {"results": [{"name": "latest"}, {"name": "99.0.0"}]}
_NEWER_PAGE = updates.RELEASES_URL + "/tag/v99.0.0"


@pytest.mark.parametrize(
    "channel, payload", [(updates.PIP, _PIP_NEWER), (updates.DOCKER, _DOCKER_NEWER)]
)
def test_a_newer_index_version_is_checked_for_a_security_release(monkeypatch, channel, payload):
    """The index and the registry carry no release notes, so the release of the version they
    found is asked whether it is a security release; otherwise most installs never see the
    badge."""
    release = {"body": "### Security\n\n- Fixed.", "html_url": _NEWER_PAGE}
    calls = _stub_channels(monkeypatch, payload, release)
    probe = updates.fetch_latest(channel)
    assert probe.error is None
    assert probe.is_security is True
    assert probe.security_unresolved is False
    assert probe.release_url == _NEWER_PAGE
    assert calls[-1] == updates.GITHUB_TAG_URL.format(tag="v99.0.0")


def test_an_ordinary_newer_release_stays_ordinary(monkeypatch):
    _stub_channels(monkeypatch, _PIP_NEWER, {"body": "### Added\n\n- A feature."})
    probe = updates.fetch_latest(updates.PIP)
    assert probe.is_security is False
    assert probe.security_unresolved is False


def test_security_in_the_prose_of_the_found_release_does_not_mark_it(monkeypatch):
    _stub_channels(monkeypatch, _PIP_NEWER, {"body": "This is not a security release."})
    assert updates.fetch_latest(updates.PIP).is_security is False


def test_no_release_lookup_when_nothing_newer_was_found(monkeypatch):
    calls = _stub_channels(monkeypatch, {"versions": ["0.0.1"]}, {"body": "### Security"})
    probe = updates.fetch_latest(updates.PIP)
    assert probe.is_security is False
    assert len(calls) == 1, "only the index may be contacted when there is nothing newer"


@pytest.mark.parametrize(
    "release_payload, release_error",
    [
        (None, urllib.error.URLError("down")),
        # A release still in draft answers 404 to an anonymous caller.
        (None, urllib.error.HTTPError("u", 404, "Not Found", {}, None)),
        (["not", "an", "object"], None),
    ],
)
def test_a_failed_release_lookup_keeps_the_found_version(
    monkeypatch, release_payload, release_error
):
    """The found update still stands, but the answer about its notes is recorded as unknown
    rather than as an ordinary release."""
    _stub_channels(monkeypatch, _PIP_NEWER, release_payload, release_error)
    probe = updates.fetch_latest(updates.PIP)
    assert probe.error is None
    assert probe.latest_version == "99.0.0"
    assert probe.is_security is False
    assert probe.security_unresolved is True


def test_the_unresolved_marker_is_part_of_the_probe_answer():
    probe = updates.UpdateProbe(source=updates.PIP, security_unresolved=True)
    assert probe.as_dict()["security_unresolved"] is True


# --- pre-releases on the index and registry channels --------------------------------------------


@pytest.mark.parametrize(
    "channel, payload",
    [
        (updates.PIP, {"versions": ["2.0.0", "2.0.1", "99.0.0rc1"]}),
        (updates.DOCKER, {"results": [{"name": "99.0.0-rc1"}, {"name": "2.0.1"}]}),
    ],
)
def test_a_stable_install_is_not_offered_a_prerelease(monkeypatch, channel, payload):
    monkeypatch.setattr(updates, "VERSION", "2.0.1")
    calls = _stub_channels(monkeypatch, payload, {"body": "### Security"})
    probe = updates.fetch_latest(channel)
    assert probe.error is None
    assert probe.latest_version == "2.0.1"
    assert not updates.is_newer(probe.latest_version, updates.VERSION)
    assert len(calls) == 1, "no release lookup when there is no update to describe"


@pytest.mark.parametrize(
    "channel, payload",
    [
        (updates.PIP, {"versions": ["2.0.1", "2.1.0a1", "2.1.0a2"]}),
        (updates.DOCKER, {"results": [{"name": n} for n in ("2.1.0a2", "2.1.0a1", "2.0.1")]}),
    ],
)
def test_a_prerelease_install_is_offered_newer_prereleases(monkeypatch, channel, payload):
    """Running a pre-release is the operator's own opt-in to them."""
    monkeypatch.setattr(updates, "VERSION", "2.1.0a1")
    _stub_channels(monkeypatch, payload, {"body": ""})
    assert updates.fetch_latest(channel).latest_version == "2.1.0a2"


# --- pre-releases on the release channel --------------------------------------------------------

_PRERELEASE_TAG = {
    "tag_name": "v2.1.0rc1",
    "body": "### Security\n\n- Fixed.",
    "html_url": updates.RELEASES_URL + "/tag/v2.1.0rc1",
}


@pytest.mark.parametrize("channel", [updates.GIT, updates.UNKNOWN])
def test_a_stable_install_is_not_offered_a_prerelease_tag(monkeypatch, channel):
    """The same rule as the index and the registry: a clone, or a source tree nobody can place,
    running a final release is not told to move to a release candidate."""
    monkeypatch.setattr(updates, "VERSION", "2.0.1")
    _stub_fetch(monkeypatch, _PRERELEASE_TAG)
    probe = updates.fetch_latest(channel)
    # Not a failed check: the newest release this install would be offered is the one it runs.
    assert probe.error is None
    assert probe.latest_version == "2.0.1"
    assert probe.is_security is False
    assert not updates.is_newer(probe.latest_version, updates.VERSION)


@pytest.mark.parametrize("channel", [updates.GIT, updates.UNKNOWN])
def test_a_prerelease_install_is_offered_a_prerelease_tag(monkeypatch, channel):
    monkeypatch.setattr(updates, "VERSION", "2.1.0a1")
    _stub_fetch(monkeypatch, _PRERELEASE_TAG)
    probe = updates.fetch_latest(channel)
    assert probe.error is None
    assert probe.latest_version == "v2.1.0rc1"
    assert probe.is_security is True
    assert updates.is_newer(probe.latest_version, updates.VERSION)


@pytest.mark.parametrize("tag", ["nightly", "v2", "release-2.1.0", "2.1", ""])
def test_a_release_tag_that_is_not_a_version_counts_as_absent(monkeypatch, tag):
    _stub_fetch(monkeypatch, {"tag_name": tag, "body": "### Security", "html_url": RELEASE_PAGE})
    probe = updates.fetch_latest(updates.GIT)
    assert probe.latest_version is None
    assert probe.error == "no_release_found"
    assert probe.is_security is False


# --- withdrawing a lookup -----------------------------------------------------------------------


def _recording_opener(monkeypatch, payload, on_open=None):
    """Answer every request with ``payload`` and record its address; ``on_open`` runs first."""
    opened = []

    def fake_urlopen(request, timeout):
        opened.append(request.full_url)
        if on_open is not None:
            on_open()
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(updates, "_urlopen", fake_urlopen)
    return opened


@pytest.mark.parametrize("channel", [updates.PIP, updates.DOCKER, updates.GIT, updates.UNKNOWN])
def test_a_lookup_withdrawn_before_it_starts_opens_no_socket(monkeypatch, caplog, channel):
    opened = _recording_opener(monkeypatch, {"versions": ["99.0.0"]})
    cancel = threading.Event()
    cancel.set()
    with caplog.at_level("INFO", logger="ipmideck.updates"):
        probe = updates.fetch_latest(channel, cancel=cancel)
    assert probe.error == "cancelled"
    assert probe.latest_version is None
    assert opened == []
    # The audit log lists the addresses contacted; a request that was never made is not one.
    assert not any("requesting" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "channel, payload", [(updates.PIP, _PIP_NEWER), (updates.DOCKER, _DOCKER_NEWER)]
)
def test_a_lookup_withdrawn_mid_way_asks_for_no_release_notes(monkeypatch, channel, payload):
    """Withdrawn while the index answer is in flight: that request finishes, the follow-up
    request for the found version's release notes is never made."""
    cancel = threading.Event()
    opened = _recording_opener(monkeypatch, payload, on_open=cancel.set)
    probe = updates.fetch_latest(channel, cancel=cancel)
    assert probe.error == "cancelled"
    assert len(opened) == 1
    assert not any("/releases/tags/" in url for url in opened)


def test_a_lookup_left_alone_still_asks_for_the_release_notes(monkeypatch):
    """The counterpart of the test above: an event that is never set changes nothing."""
    opened = _recording_opener(monkeypatch, _PIP_NEWER)
    probe = updates.fetch_latest(updates.PIP, cancel=threading.Event())
    assert probe.error is None
    assert probe.latest_version == "99.0.0"
    assert opened[-1] == updates.GITHUB_TAG_URL.format(tag="v99.0.0")


def test_a_withdrawn_lookup_follows_no_further_redirect(monkeypatch):
    """A redirect opens another socket, so it is a request like any other. The first hop is
    followed; the lookup is withdrawn; the second hop is refused."""
    cancel = threading.Event()
    handler = updates._UpdateEndpointRedirects()
    hops = []

    def redirected_twice(request, timeout):
        first = handler.redirect_request(
            request, None, 301, "Moved", {}, "https://api.github.com/repositories/1/releases/latest"
        )
        hops.append(first.full_url)
        cancel.set()
        second = handler.redirect_request(
            first, None, 301, "Moved", {}, "https://api.github.com/repositories/2/releases/latest"
        )
        hops.append(second.full_url)
        return _FakeResponse(json.dumps({"tag_name": "v99.0.0"}).encode())

    monkeypatch.setattr(updates, "_urlopen", redirected_twice)
    probe = updates.fetch_latest(updates.GIT, cancel=cancel)
    assert probe.error == "cancelled"
    assert hops == ["https://api.github.com/repositories/1/releases/latest"]


# --- release links and redirects ----------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate, accepted",
    [
        (updates.RELEASES_URL + "/tag/v2.1.0", True),
        ("javascript:alert(1)", False),
        ("https://evil.example/ipmideck/IPMIDeck/releases/tag/v2", False),
        (updates.RELEASES_URL + ".evil.example/x", False),
        ("http://github.com/ipmideck/IPMIDeck/releases/tag/v2", False),
        (None, False),
        (42, False),
    ],
)
def test_only_a_release_page_of_this_project_is_kept_as_a_link(candidate, accepted):
    expected = candidate if accepted else updates.RELEASES_URL
    assert updates.safe_release_url(candidate) == expected


def test_a_foreign_link_in_the_release_answer_is_not_passed_on(monkeypatch):
    _stub_fetch(monkeypatch, {"tag_name": "v9.9.9", "body": "", "html_url": "javascript:alert(1)"})
    assert updates.fetch_latest(updates.GIT).release_url == updates.RELEASES_URL


@pytest.mark.parametrize(
    "target",
    [
        "http://pypi.org/simple/ipmideck/",
        "https://evil.example/simple/ipmideck/",
        "ftp://pypi.org/simple/ipmideck/",
    ],
)
def test_a_redirect_off_the_update_endpoints_is_refused(target):
    handler = updates._UpdateEndpointRedirects()
    request = urllib.request.Request(updates.PYPI_URL)
    with pytest.raises(ValueError):
        handler.redirect_request(request, None, 302, "Found", {}, target)


def test_a_redirect_between_update_endpoints_is_followed_and_logged(caplog):
    handler = updates._UpdateEndpointRedirects()
    request = urllib.request.Request(updates.GITHUB_URL)
    target = "https://api.github.com/repositories/1/releases/latest"
    with caplog.at_level("INFO", logger="ipmideck.updates"):
        followed = handler.redirect_request(request, None, 301, "Moved", {}, target)
    assert followed.full_url == target
    assert any(target in r.getMessage() for r in caplog.records)


def test_a_redirect_off_the_endpoints_ends_as_a_reason_not_a_request(monkeypatch):
    def redirected(request, timeout):
        return updates._UpdateEndpointRedirects().redirect_request(
            request, None, 302, "Found", {}, "http://pypi.org/simple/ipmideck/"
        )

    monkeypatch.setattr(updates, "_urlopen", redirected)
    assert updates.fetch_latest(updates.PIP).error == "invalid_response"


def test_a_target_off_the_endpoints_is_never_opened(monkeypatch):
    opened = []
    monkeypatch.setattr(updates, "_urlopen", lambda *a, **k: opened.append(a))
    with pytest.raises(ValueError):
        updates._fetch("https://evil.example/x", "application/json", 1.0)
    assert opened == []


def test_the_opener_uses_the_restricted_redirect_handler():
    handlers = updates._OPENER.handlers
    assert any(isinstance(h, updates._UpdateEndpointRedirects) for h in handlers)
    # The stock handler would follow anything; it must not sit beside ours.
    assert not any(
        type(h) is urllib.request.HTTPRedirectHandler for h in handlers
    )
