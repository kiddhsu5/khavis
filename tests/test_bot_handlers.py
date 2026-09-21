"""Unit tests for the bot handlers (command parsing)."""
from __future__ import annotations

from bot.handlers import is_allowed, parse_run_command
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
        only, cap, prompt = parse_run_command(
            "/run --only codex --capability=reasoning explain"
        )
        assert only == ["codex"]
        assert cap == "reasoning"
        assert prompt == "explain"

    def test_empty_prompt(self):
        only, cap, prompt = parse_run_command("/run")
        assert only is None
        assert prompt == ""

    def test_quoted_prompt_with_spaces(self):
        only, cap, prompt = parse_run_command(
            '/run --only codex "fix the flaky test"'
        )
        assert only == ["codex"]
        assert prompt == "fix the flaky test"


class TestIncomingMessageModel:
    def test_command_flag(self):
        m = IncomingMessage(
            update_id=1, chat_id=10, user_id=20, text="/help", is_command=True
        )
        assert m.is_command is True

    def test_default_user_id_none(self):
        m = IncomingMessage(update_id=2, chat_id=10, text="hi")
        assert m.user_id is None
