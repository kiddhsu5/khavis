"""Tests for Phase 4 runner, history, and dashboard renderers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bot import history as bot_history
from bot.phases import PHASES, run_phase
from web.dashboard import api_payload, render_dashboard_html, render_wall_html


class TestHistory:
    def test_record_and_tail(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("KHAVIS_LOG_DIR", str(tmp_path))
        bot_history.record({"kind": "dispatch", "ok": True, "prompt": "hello"})
        bot_history.record({"kind": "phase", "phase": "plan", "ok": False, "prompt": "x"})
        rows = bot_history.tail(10)
        assert len(rows) == 2
        assert rows[0]["kind"] == "phase"  # newest first
        assert rows[1]["prompt"] == "hello"

    def test_truncates_long_fields(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("KHAVIS_LOG_DIR", str(tmp_path))
        bot_history.record({"prompt": "A" * 5000})
        row = bot_history.tail(1)[0]
        assert len(row["prompt"]) < 2100

    def test_tail_missing_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("KHAVIS_LOG_DIR", str(tmp_path / "nope"))
        assert bot_history.tail() == []


class TestPhases:
    def test_phase_names(self):
        names = [n for n, _ in PHASES]
        assert "plan" in names and "code" in names
        assert "pipeline" not in names  # virtual stage in run_phase()


    def test_unknown_phase(self):
        r = asyncio.run(run_phase("nope", "hi"))
        assert r.ok is False
        assert "unknown phase" in r.error

    def test_plan_phase_uses_run_team(self, monkeypatch):
        calls = {}

        def fake_run_team(task, session_id="default"):
            calls["task"] = task
            return {"plan": "do the thing", "error": ""}

        import agents

        monkeypatch.setattr(agents, "run_team", fake_run_team)
        r = asyncio.run(run_phase("plan", "write a parser", on_progress=None))
        assert r.ok is True
        assert "do the thing" in r.output
        assert "[phase:plan]" in calls["task"]


class TestDashboard:
    def test_api_payload_shape(self):
        p = api_payload(pools=[{"name": "X", "ok": True}], bot={"ok": True}, history=[])
        assert "pools" in p and "wall" in p and "history" in p

    def test_render_dashboard_contains_wall_and_pools(self):
        html = render_dashboard_html(
            pools=[{"name": "MiMo-Code", "provider_id": "mimo", "ok": True, "models": ["mimo-v2.6-pro"], "capabilities": ["code"]}],
            bot={"ok": True, "detail": "active"},
            history=[{"kind": "dispatch", "ok": True, "prompt": "hi", "latency_ms": 10, "ts": 0}],
        )
        assert "MiMo-Code" in html
        assert "個人開發者 wall" in html
        assert "dashboard" in html

    def test_render_wall(self):
        html = render_wall_html([{"label": "alice", "detail": "homelab", "url": "https://example.com"}])
        assert "alice" in html and "homelab" in html
