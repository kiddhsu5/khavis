"""Unit tests for the subprocess backend wrappers (arg building + JSON parsing)."""

from __future__ import annotations

import json

from bot.backends.claude import _parse_claude_json


class TestParseClaudeJson:
    def test_real_claude_code_json_shape(self):
        """``claude -p --output-format json`` puts the answer in ``result``.

        Regression guard: the parser used to look only for ``text`` /
        ``content`` / ``output`` and so returned an empty string for every
        real Claude Code response.
        """
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "OK",
            "usage": {"input_tokens": 3352, "output_tokens": 2455},
            "modelUsage": {"mimo-v2.6-pro": {"contextWindow": 200000}},
        }
        text, model, tok_in, tok_out = _parse_claude_json(json.dumps(payload), "hi")
        assert text == "OK"
        assert model == "mimo-v2.6-pro"
        assert tok_in == 3352
        assert tok_out == 2455

    def test_model_field_wins_over_model_usage(self):
        payload = {"result": "x", "model": "claude-opus-5", "modelUsage": {"other": {}}}
        _, model, _, _ = _parse_claude_json(json.dumps(payload), "")
        assert model == "claude-opus-5"

    def test_text_fallback_keys_still_work(self):
        assert _parse_claude_json(json.dumps({"text": "a"}), "")[0] == "a"
        assert _parse_claude_json(json.dumps({"content": "b"}), "")[0] == "b"
        assert _parse_claude_json(json.dumps({"output": "c"}), "")[0] == "c"

    def test_non_json_falls_back_to_raw(self):
        text, model, tok_in, tok_out = _parse_claude_json("just plain text", "")
        assert text == "just plain text"
        assert model == ""
        assert (tok_in, tok_out) == (0, 0)

    def test_empty_input(self):
        assert _parse_claude_json("", "p") == ("", "", 0, 0)
        assert _parse_claude_json("   ", "p") == ("", "", 0, 0)

    def test_usage_alias_keys(self):
        payload = {"result": "x", "usage": {"input": 7, "output": 9}}
        _, _, tok_in, tok_out = _parse_claude_json(json.dumps(payload), "")
        assert (tok_in, tok_out) == (7, 9)
