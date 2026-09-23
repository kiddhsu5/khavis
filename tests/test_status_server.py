"""Tests for the public khavis status page.

The page is world-readable, so the only hard requirement here is that
``_redact`` never lets a credential-shaped string through. Everything
else is presentation.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import scripts.status_server as status_server
from scripts.status_server import (
    _probe_plugins,
    _redact,
    candidate_hosts,
    ensure_self_signed_cert,
    pool_health,
    primary_ipv4,
    render_html,
    resolve_cert_paths,
    start_listener,
)


class _FakePlug:
    """Minimal ProviderPlugin stand-in with a controllable health latency."""

    def __init__(self, name: str, delay: float, ok: bool = True):
        self.name = name
        self.provider_id = "fake"
        self.capabilities = ["中文"]
        self._delay = delay
        self._ok = ok

    def health_check(self):
        time.sleep(self._delay)
        return {"ok": self._ok, "detail": f"probe {self.name}"}

    def list_models(self):
        return ["fake-1"]


class TestRedact:
    def test_strips_key_present_flag(self):
        out = _redact("endpoint=https://x model=m key_present=True")
        assert "key_present" not in out
        assert "[redacted]" in out
        # Non-secret context survives.
        assert "endpoint=https://x" in out

    def test_strips_anthropic_style_key(self):
        out = _redact("auth failed sk-ant-api03-ABCDEFGHIJKLmnop")
        assert "sk-ant" not in out
        assert "ABCDEFGHIJKLmnop" not in out

    def test_strips_github_token(self):
        out = _redact("bad credential ghp_ABCDEFGHIJKLmnop123456")
        assert "ghp_" not in out
        assert "ABCDEFGHIJKLmnop123456" not in out

    def test_strips_bearer_header(self):
        out = _redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload")
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert "Bearer eyJ" not in out

    def test_strips_key_value_pairs(self):
        for sample in (
            "api_key=AIzaSyDummyValue12345",
            "token: abcdefghijklmnop",
            "secret=supersecretvalue",
            "password=hunter2hunter2",
        ):
            out = _redact(sample)
            assert out != sample, sample
            assert "supersecretvalue" not in out
            assert "hunter2hunter2" not in out

    def test_strips_long_blobs(self):
        blob = "a" * 64
        out = _redact(f"cookie={blob}")
        assert blob not in out

    def test_keeps_plain_text(self):
        s = "models/gemini-2.5-flash is no longer available (404)"
        assert _redact(s) == s

    def test_idempotent_on_clean_input(self):
        s = "endpoint=http://localhost:11434 status=200"
        assert _redact(_redact(s)) == s

    def test_empty_string(self):
        assert _redact("") == ""


class TestRender:
    def _rows(self):
        return [
            {
                "name": "MiniMax-M3",
                "provider_id": "minimax",
                "models": ["MiniMax-M3"],
                "capabilities": ["中文"],
                "ok": True,
                "detail": "key_present=True api_key=sk-ant-SHOULD_NEVER_APPEAR",
            },
            {
                "name": "Broken",
                "provider_id": "x",
                "models": [],
                "capabilities": [],
                "ok": False,
                "detail": _redact("boom token=abcdefghijklmnop"),
            },
        ]

    def test_html_escapes_detail(self):
        rows = self._rows()
        rows[0]["detail"] = "<script>alert(1)</script>"
        out = render_html(rows, {"ok": False, "detail": "<img onerror=x>"})
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_summary_counts(self):
        out = render_html(self._rows(), {"ok": True, "detail": "active"})
        assert "1 / 2" in out

    def test_renders_without_rows(self):
        out = render_html([], {"ok": False, "detail": "n/a"})
        assert "0 / 0" in out
        assert "<table>" in out

    def test_bot_detail_is_escaped(self):
        out = render_html([], {"ok": False, "detail": "</p><script>"})
        assert "</p><script>" not in out

    def test_redacts_before_render(self):
        # render_html trusts its caller's ``detail``, so the caller
        # (pool_health) must redact — pin that contract here.
        rows = [{"name": "A", "provider_id": "b", "models": [], "capabilities": [], "ok": False,
                 "detail": _redact("api_key=AIzaSyDummyValue12345")}]
        out = render_html(rows, {"ok": False, "detail": ""})
        assert "AIzaSyDummyValue12345" not in out

    def test_healthz_payload_is_json_serialisable(self):
        rows = self._rows()
        payload = {"ok": False, "bot": {"ok": True, "detail": "x"}, "pools": rows}
        parsed = json.loads(json.dumps(payload, ensure_ascii=False))
        assert len(parsed["pools"]) == 2


class TestSelfSignedCert:
    def test_no_op_when_cert_already_present(self, tmp_path: Path):
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        cert.write_text("x")
        key.write_text("y")
        with patch("scripts.status_server.subprocess.run") as run:
            assert ensure_self_signed_cert(cert, key) is True
        run.assert_not_called()

    def test_mints_keypair_when_missing(self, tmp_path: Path):
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        assert ensure_self_signed_cert(cert, key) is True
        assert cert.exists() and key.exists()
        # Private key must not be world-readable.
        assert (key.stat().st_mode & 0o077) == 0

    def test_reuses_existing_keypair(self, tmp_path: Path):
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        assert ensure_self_signed_cert(cert, key) is True
        first = cert.read_text()
        cert.write_text("mutated")
        with patch("scripts.status_server.subprocess.run") as run:
            assert ensure_self_signed_cert(cert, key) is True
        run.assert_not_called()
        assert cert.read_text() == "mutated"

    def test_returns_false_when_openssl_fails(self, tmp_path: Path):
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        with patch("scripts.status_server.subprocess.run", side_effect=OSError("no openssl")):
            assert ensure_self_signed_cert(cert, key) is False
        assert not cert.exists()


class TestResolveCertPaths:
    def test_creates_parent_and_keeps_paths(self, tmp_path: Path):
        cert, key = tmp_path / "sub" / "cert.pem", tmp_path / "sub" / "key.pem"
        got_cert, got_key = resolve_cert_paths(cert, key)
        assert (got_cert, got_key) == (cert, key)
        assert cert.parent.is_dir()

    def test_falls_back_to_temp_dir_when_unwritable(self, tmp_path: Path):
        # A path whose parent is an existing *file* cannot be mkdir'd.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        cert, key = blocker / "cert.pem", blocker / "key.pem"
        got_cert, got_key = resolve_cert_paths(cert, key)
        assert got_cert != cert
        assert got_cert.parent.is_dir() and got_key.parent == got_cert.parent
        assert got_cert.name == "cert.pem" and got_key.name == "key.pem"
        # And the fallback is actually usable end to end.
        assert ensure_self_signed_cert(got_cert, got_key) is True
        assert got_cert.exists() and got_key.exists()


class TestCandidateHosts:
    def test_explicit_host_is_not_expanded(self):
        assert candidate_hosts("127.0.0.1") == ["127.0.0.1"]

    def test_wildcard_starts_wildcard_and_ends_loopback(self):
        hosts = candidate_hosts("0.0.0.0")
        assert hosts[0] == "0.0.0.0"
        assert hosts[-1] == "127.0.0.1"
        assert len(hosts) == len(set(hosts))

    def test_never_returns_public_loopback_early(self):
        hosts = candidate_hosts("0.0.0.0")
        # 127.x may only be the last resort, otherwise a clash would
        # silently downgrade the service to loopback-only.
        assert all(not h.startswith("127.") for h in hosts[:-1])

    def test_primary_ipv4_is_fast_and_not_loopback(self):
        # This must never block on DNS — a stall here delays boot.
        import time

        t0 = time.monotonic()
        addr = primary_ipv4()
        assert time.monotonic() - t0 < 1.0
        assert addr is None or not addr.startswith("127.")


class TestStartListener:
    def test_binds_and_serves(self):
        got = start_listener("http", "127.0.0.1", 0)
        assert got is not None
        label, srv, thread = got
        assert label == "http://127.0.0.1"
        assert srv.server_address[1] > 0
        try:
            thread.start()
            srv.shutdown()  # only valid once serve_forever is running
        finally:
            srv.server_close()

    def test_port_clash_returns_none_instead_of_raising(self):
        first = start_listener("http", "127.0.0.1", 0)
        assert first is not None
        _label, srv, _thread = first
        port = srv.server_address[1]
        try:
            # Same concrete address and port: the fallback list has only
            # one entry, so this must degrade to None, not raise.
            assert start_listener("http", "127.0.0.1", port) is None
        finally:
            # server_close(), not shutdown() — shutdown() waits on an
            # event that only serve_forever() sets, so calling it on a
            # thread we never started deadlocks the test run.
            srv.server_close()

    def test_one_dead_listener_does_not_affect_the_other(self):
        # Regression: a bind failure used to propagate out of main() and
        # kill the listener that had already started successfully.
        good = start_listener("http", "127.0.0.1", 0)
        assert good is not None
        _label, srv, _thread = good
        try:
            dead = start_listener("https", "127.0.0.1", srv.server_address[1])
            assert dead is None
            # The healthy listener is still intact and usable.
            assert srv.socket.fileno() >= 0
        finally:
            srv.server_close()


class TestHealthCache:
    """A sweep of 12 pools waits on the slowest unreachable one.

    Stale-while-revalidate is what keeps visitors off that timeout path.
    """

    def setup_method(self):
        status_server._HEALTH_CACHE = (None, 0.0)
        status_server._REFRESHING = False

    def teardown_method(self):
        status_server._HEALTH_CACHE = (None, 0.0)
        status_server._REFRESHING = False

    @staticmethod
    def _age_cache_by(seconds: float) -> None:
        rows, _ts = status_server._HEALTH_CACHE
        status_server._HEALTH_CACHE = (rows, time.monotonic() - seconds)

    @staticmethod
    def _wait_for(predicate, timeout: float = 3.0) -> bool:
        """Poll until predicate() is true. Returns whether it happened.

        Not ``probe.call_count``: the refresher calls _probe_all_pools
        *before* it writes the cache, so waiting on the call count races
        the assignment.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_first_call_blocks_and_populates(self):
        sentinel = [{"name": "x", "ok": True, "detail": "", "models": [], "capabilities": [], "provider_id": ""}]
        with patch.object(status_server, "_probe_all_pools", return_value=sentinel) as probe:
            assert pool_health() is sentinel
        assert probe.call_count == 1

    def test_second_call_hits_the_cache(self):
        with patch.object(status_server, "_probe_all_pools", return_value=[]) as probe:
            pool_health()
            pool_health()
        assert probe.call_count == 1

    def test_stale_value_is_served_without_waiting(self):
        # The whole point: a TTL expiry must not put a 20s probe in front
        # of the visitor who happened to hit right after it lapsed.
        first = [{"name": "old", "ok": True, "detail": "", "models": [], "capabilities": [], "provider_id": ""}]
        second = [{"name": "new", "ok": True, "detail": "", "models": [], "capabilities": [], "provider_id": ""}]
        gate = threading.Event()
        n = 0

        def probe_fn():
            nonlocal n
            n += 1
            if n == 1:
                return first
            gate.wait(timeout=5)  # hold the refresher until we say so
            return second

        with patch.object(status_server, "_probe_all_pools", side_effect=probe_fn) as probe:
            assert pool_health() is first
            self._age_cache_by(status_server.CACHE_TTL + 1)
            t0 = time.monotonic()
            assert pool_health() is first  # stale, served immediately
            assert time.monotonic() - t0 < 0.2
            assert probe.call_count == 2  # the refresher did start
            gate.set()
            assert self._wait_for(lambda: pool_health() is second)
            assert pool_health() is second

    def test_concurrent_stale_hits_start_only_one_refresh(self):
        with patch.object(status_server, "_probe_all_pools", return_value=[]) as probe:
            pool_health()
            self._age_cache_by(status_server.CACHE_TTL + 1)

            slow = threading.Event()

            def blocking():
                slow.wait(timeout=5)
                return []

            with patch.object(status_server, "_probe_all_pools", side_effect=blocking) as probe2:
                threads = [threading.Thread(target=pool_health) for _ in range(12)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=2)
                slow.set()
                # Give a second, unwanted refresh a chance to appear.
                time.sleep(0.2)
            assert probe2.call_count == 1, "single-flight failed"
            assert probe.call_count == 1

    def test_ttl_is_long_enough_to_absorb_timeouts(self):
        # Below ~10s a single slow probe would still dominate refreshes.
        assert status_server.CACHE_TTL >= 10.0

    def test_probes_run_in_parallel_not_serially(self):
        # 8 pools x 0.3s = 2.4s if serial. Against a real ThreadPool this
        # must land near the single-probe latency instead.
        plugs = [_FakePlug(f"p{i}", delay=0.3) for i in range(8)]
        t0 = time.monotonic()
        rows = _probe_plugins(plugs)
        elapsed = time.monotonic() - t0
        assert len(rows) == 8
        assert elapsed < 1.0, f"probing looked serial ({elapsed:.2f}s)"

    def test_probe_preserves_order(self):
        plugs = [_FakePlug(f"p{i}", delay=0.0) for i in range(5)]
        rows = _probe_plugins(plugs)
        assert [r["name"] for r in rows] == [f"p{i}" for i in range(5)]

    def test_probe_redacts_detail(self):
        rows = _probe_plugins([_SafeDetailPlug("api_key=AIzaSyDummyValue12345")])
        assert "AIzaSyDummyValue12345" not in rows[0]["detail"]

    def test_probe_survives_a_raising_plugin(self):
        class Boom:
            name = "boom"
            provider_id = "fake"
            capabilities = []

            def health_check(self):
                raise RuntimeError("api_key=AIzaSyDummyValue12345")

            def list_models(self):
                return []

        rows = _probe_plugins([_FakePlug("ok", 0.0), Boom()])
        assert rows[0]["ok"] is True
        assert rows[1]["ok"] is False
        assert "RuntimeError" in rows[1]["detail"]
        assert "AIzaSyDummyValue12345" not in rows[1]["detail"]

    def test_probe_handles_empty_plugin_list(self):
        assert _probe_plugins([]) == []


class _SafeDetailPlug(_FakePlug):
    """A plugin whose health detail is hostile input for _redact."""

    def __init__(self, detail: str):
        super().__init__("hostile", delay=0.0)
        self._detail = detail

    def health_check(self):
        return {"ok": False, "detail": self._detail}
