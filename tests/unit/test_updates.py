"""Update-lookup core: version ordering, install-method detection, and the channel fetchers."""

from __future__ import annotations

import http.client
import json
import pathlib
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

    def fake(url, accept, timeout):
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

    def boom(url, accept, timeout):
        raise raised

    monkeypatch.setattr(updates, "_fetch", boom)
    probe = updates.fetch_latest(updates.PIP)
    assert probe.error == expected
    assert probe.latest_version is None


def test_an_oversized_response_is_refused(monkeypatch):
    """The body is valid JSON, so only the size bound can refuse it; and the read itself has to
    be bounded, or the check runs after the memory is already spent."""
    head, tail = b'{"versions": ["0.0.1"], "padding": "', b'"}'
    body = head + b"x" * (updates._MAX_RESPONSE_BYTES + 1 - len(head) - len(tail)) + tail
    assert len(body) == updates._MAX_RESPONSE_BYTES + 1
    assert json.loads(body)["versions"] == ["0.0.1"]
    response = _serve(monkeypatch, body)
    assert updates.fetch_latest(updates.PIP).error == "invalid_response"
    assert response.requested, "the body was never read"
    assert all(0 <= n <= updates._MAX_RESPONSE_BYTES + 1 for n in response.requested)


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

    def fake(url, accept, timeout):
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


def test_a_prerelease_install_is_offered_newer_prereleases(monkeypatch):
    """Running a pre-release is the operator's own opt-in to them."""
    monkeypatch.setattr(updates, "VERSION", "2.1.0a1")
    _stub_channels(monkeypatch, {"versions": ["2.0.1", "2.1.0a1", "2.1.0a2"]}, {"body": ""})
    assert updates.fetch_latest(updates.PIP).latest_version == "2.1.0a2"


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
