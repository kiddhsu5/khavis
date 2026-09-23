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

from scripts.status_server import _redact, render_html


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
