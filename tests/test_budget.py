"""Tests for core.budget (v0.2.0 token-aware cost budget)."""

from __future__ import annotations

from pathlib import Path

from core.budget import (
    BudgetGuard,
    BudgetPolicy,
    estimate_tokens,
    get_guard,
    load_policy,
    reset_guard,
)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x" * 400) == 100


def test_load_policy_defaults(tmp_path: Path):
    p = tmp_path / "budgets.yaml"
    p.write_text(
        """
policy:
  max_tokens_per_request: 100
  max_tokens_per_session: 1000
  max_cost_per_session_usd: 0
  window_s: 60
pricing_usd_per_1k:
  X: 1.0
""",
        encoding="utf-8",
    )
    pol = load_policy(p)
    assert pol.max_tokens_per_request == 100
    assert pol.pricing_usd_per_1k["X"] == 1.0


def test_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KHAVIS_BUDGET_MAX_TOKENS_REQUEST", "777")
    pol = load_policy(tmp_path / "missing.yaml")
    assert pol.max_tokens_per_request == 777


def test_request_cap_blocks():
    guard = BudgetGuard(BudgetPolicy(max_tokens_per_request=10, max_tokens_per_session=10**9))
    assert guard.allow(session_id="s", pool="P", prompt_chars=8) is True
    assert guard.allow(session_id="s", pool="P", prompt_chars=8000) is False
    assert "max_tokens_per_request" in guard.reason()


def test_session_token_cap():
    guard = BudgetGuard(
        BudgetPolicy(max_tokens_per_request=10_000, max_tokens_per_session=100, window_s=3600)
    )
    guard.record(session_id="s", pool="P", usage={"prompt_tokens": 90, "completion_tokens": 0})
    assert guard.allow(session_id="s", pool="P", prompt_chars=80) is False
    assert "max_tokens_per_session" in guard.reason()
    # other session unaffected
    assert guard.allow(session_id="other", pool="P", prompt_chars=4) is True


def test_session_cost_cap():
    guard = BudgetGuard(
        BudgetPolicy(
            max_tokens_per_request=10_000,
            max_tokens_per_session=10**9,
            max_cost_per_session_usd=0.01,
            pricing_usd_per_1k={"X": 10.0},  # $10 / 1k tokens
        )
    )
    # 20 tokens ≈ $0.2 — already over
    guard.record(session_id="s", pool="X", usage={"prompt_tokens": 20, "completion_tokens": 0})
    assert guard.allow(session_id="s", pool="X", prompt_chars=4) is False
    assert "max_cost_per_session_usd" in guard.reason()


def test_window_prunes_old_events():
    guard = BudgetGuard(BudgetPolicy(max_tokens_per_session=50, window_s=0.01))
    guard.record(session_id="s", pool="P", usage={"prompt_tokens": 40, "completion_tokens": 0})
    import time

    time.sleep(0.02)
    assert guard.allow(session_id="s", pool="P", prompt_chars=4) is True


def test_status_shape():
    guard = BudgetGuard()
    guard.record(session_id="s", pool="MiMo-Code", usage={"prompt_tokens": 5, "completion_tokens": 5})
    st = guard.status()
    assert "policy" in st and "sessions" in st and "by_pool" in st
    assert st["sessions"]["s"]["tokens"] == 10
    assert "MiMo-Code" in st["by_pool"]


def test_singleton_reset():
    g1 = get_guard()
    g2 = reset_guard(BudgetPolicy(max_tokens_per_request=1))
    assert g2 is get_guard()
    assert g2.policy.max_tokens_per_request == 1
    assert g2 is not g1
