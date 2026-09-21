"""Unit tests for the dispatch aggregator and synthesis logic."""
from __future__ import annotations

from bot.aggregator import format_report
from bot.dispatch import synthesize
from bot.models import BackendResult, DispatchEnvelope, DispatchReport


def _env(prompt: str = "p") -> DispatchEnvelope:
    return DispatchEnvelope(chat_id=1, prompt=prompt)


class TestSynthesize:
    def test_picks_longest_above_threshold(self):
        r1 = BackendResult(backend="claude", ok=True, text="a" * 30, model="m")
        r2 = BackendResult(backend="codex", ok=True, text="b" * 25, model="m")
        r3 = BackendResult(backend="llm-router", ok=True, text="c" * 20, model="m")
        text, source = synthesize([r1, r2, r3])
        assert text == "a" * 30
        assert source == "claude"

    def test_falls_back_to_first_when_all_short(self):
        r1 = BackendResult(backend="claude", ok=True, text="hi", model="m")
        r2 = BackendResult(backend="codex", ok=True, text="hey", model="m")
        text, source = synthesize([r1, r2])
        assert text in ("hi", "hey")
        assert source in ("claude", "codex")

    def test_skips_failures(self):
        ok = BackendResult(backend="claude", ok=True, text="a" * 50, model="m")
        bad = BackendResult(backend="codex", ok=False, error="boom", model="m")
        text, source = synthesize([bad, ok])
        assert text == "a" * 50
        assert source == "claude"

    def test_all_failures_returns_empty(self):
        bad1 = BackendResult(backend="claude", ok=False, error="x", model="m")
        bad2 = BackendResult(backend="codex", ok=False, error="y", model="m")
        text, source = synthesize([bad1, bad2])
        assert text == ""
        assert source == ""


class TestFormatReport:
    def test_renders_header_and_each_block(self):
        report = DispatchReport(
            envelope=_env("hello"),
            results=[
                BackendResult(backend="claude", ok=True, text="a" * 30, model="m1"),
                BackendResult(backend="codex", ok=False, error="boom", model="m2"),
            ],
            consensus="a" * 30,
            consensus_source="claude",
        )
        text = format_report(report)
        assert "/run: hello" in text
        assert "claude" in text
        assert "boom" in text
        assert "consensus" in text.lower()

    def test_empty_results_still_renders(self):
        report = DispatchReport(envelope=_env(), results=[], consensus="", consensus_source="")
        text = format_report(report)
        assert "/run" in text
        assert "no backend" in text.lower()

    def test_truncates_long_prompt(self):
        long_prompt = "x" * 500
        report = DispatchReport(
            envelope=_env(long_prompt),
            results=[BackendResult(backend="claude", ok=True, text="ok", model="m")],
            consensus="ok",
            consensus_source="claude",
        )
        text = format_report(report)
        # Long prompt should be truncated with …
        assert "…" in text
        # And no single line is absurdly long
        assert max(len(line) for line in text.splitlines()) <= 300
