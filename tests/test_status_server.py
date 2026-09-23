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
from pathlib import Path
from unittest.mock import patch

from scripts.status_server import (
    _redact,
    candidate_hosts,
    ensure_self_signed_cert,
    primary_ipv4,
    render_html,
    resolve_cert_paths,
    start_listener,
)


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
