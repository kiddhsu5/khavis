"""Unit tests for the bot handlers (command parsing)."""

from __future__ import annotations

from bot.handlers import (
    handle_run,
    is_allowed,
    parse_run_command,
    route_command,
)
from bot.models import IncomingMessage


class TestIsAllowed:
    def test_empty_allowlist_denies_everyone(self):
        assert is_allowed(123, []) is False

    def test_allowlist_accepts_match(self):
        assert is_allowed(123, [123, 456]) is True

    def test_allowlist_rejects_nonmatch(self):
        assert is_allowed(789, [123, 456]) is False


class TestParseRun:
    def test_basic_prompt(self):
        only, cap, prompt = parse_run_command("/run hello world")
        assert only is None
        assert cap is None
        assert prompt == "hello world"

    def test_only_subset(self):
        only, cap, prompt = parse_run_command("/run --only codex,claude ping")
        assert only == ["codex", "claude"]
        assert cap is None
        assert prompt == "ping"

    def test_capability_flag(self):
        only, cap, prompt = parse_run_command("/run --capability code fix bug")
        assert only is None
        assert cap == "code"
        assert prompt == "fix bug"

    def test_capability_equals_form(self):
        only, cap, prompt = parse_run_command("/run --capability=code fix bug")
        assert cap == "code"
        assert prompt == "fix bug"

    def test_only_with_capability(self):
        only, cap, prompt = parse_run_command("/run --only codex --capability=reasoning explain")
        assert only == ["codex"]
        assert cap == "reasoning"
        assert prompt == "explain"

    def test_empty_prompt(self):
        only, cap, prompt = parse_run_command("/run")
        assert only is None
        assert prompt == ""

    def test_quoted_prompt_with_spaces(self):
        only, cap, prompt = parse_run_command('/run --only codex "fix the flaky test"')
        assert only == ["codex"]
        assert prompt == "fix the flaky test"

    # --- natural-language path: no ``/run`` prefix required ---

    def test_natural_language_prompt(self):
        """Bare prose is dispatched as-is with no flags set."""
        only, cap, prompt = parse_run_command("write a Python function to average a list")
        assert only is None
        assert cap is None
        assert prompt == "write a Python function to average a list"

    def test_natural_language_preserves_unicode(self):
        only, cap, prompt = parse_run_command("寫一個 Python function 計算 list 平均值")
        assert only is None
        assert cap is None
        assert prompt == "寫一個 Python function 計算 list 平均值"

    def test_natural_language_preserves_inner_slashes(self):
        """A path like ``a/b/c`` in prose should not be mistaken for a flag."""
        only, cap, prompt = parse_run_command("explain the difference between a/b and c/d")
        assert only is None
        assert cap is None
        assert prompt == "explain the difference between a/b and c/d"

    def test_run_prefix_is_case_insensitive(self):
        only, cap, prompt = parse_run_command("/RUN hello")
        assert only is None
        assert prompt == "hello"


class TestRouteCommand:
    def test_known_commands_route_to_their_handlers(self):
        assert route_command("/help").__name__ == "handle_help"
        assert route_command("/start").__name__ == "handle_start"
        assert route_command("/status").__name__ == "handle_status"
        assert route_command("/pools").__name__ == "handle_pools"
        assert route_command("/run hi").__name__ == "handle_run"

    def test_run_routes_to_handle_run(self):
        assert route_command("/run ping") is handle_run

    def test_natural_language_routes_to_handle_run(self):
        """Bare prose dispatches — no ``/run`` prefix required."""
        assert route_command("hello") is handle_run
        assert route_command("寫一個 quicksort") is handle_run

    def test_unknown_slash_command_returns_none(self):
        """Typos like ``/statu`` should NOT silently fan out to backends."""
        assert route_command("/statu") is None
        assert route_command("/unknown") is None
        assert route_command("/RUN--with-typo") is None

    def test_empty_text_returns_none(self):
        assert route_command("") is None
        assert route_command("   ") is None


class TestIncomingMessageModel:
    def test_command_flag(self):
        m = IncomingMessage(update_id=1, chat_id=10, user_id=20, text="/help", is_command=True)
        assert m.is_command is True

    def test_default_user_id_none(self):
        m = IncomingMessage(update_id=2, chat_id=10, text="hi")
        assert m.user_id is None
