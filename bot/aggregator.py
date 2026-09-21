"""Render a ``DispatchReport`` as a single Telegram MarkdownV2 message."""

from __future__ import annotations

from .models import DispatchReport
from .telegram_api import TelegramAPI


def format_report(report: DispatchReport) -> str:
    """Single-message MarkdownV2 view of per-backend outcomes + consensus."""
    prompt = TelegramAPI.escape_markdown_v2(_truncate(report.envelope.prompt, 200))
    lines: list[str] = [f"🔁 /run: {prompt}", ""]
    for r in report.results:
        lines.append(TelegramAPI.format_result_block(r))
        lines.append("")
    if report.consensus:
        src = TelegramAPI.escape_markdown_v2(str(report.consensus_source))
        body = TelegramAPI.escape_markdown_v2(_truncate(report.consensus, 3000))
        lines.append(f"🏁 *consensus* \\(from `{src}`\\):\n{body}")
    else:
        lines.append("⚠️ _no backend produced a usable answer_")
    text = "\n".join(lines).rstrip()
    # Telegram has a 4096-char hard limit per message; the
    # ``escape_markdown_v2`` + per-block 1500-char cap keeps us under it
    # for any realistic reply.
    return text[:4000]


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"
