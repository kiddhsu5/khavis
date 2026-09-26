"""Operator web dashboard + personal-developer wall.

Pure renderers — no framework, no build step. `scripts/status_server.py`
and the bot FastAPI app both call :func:`render_dashboard_html` /
:func:`api_payload`. The wall is README-facing HTML and also serves at
``/wall`` for a live stargazer strip.
"""

from __future__ import annotations

import html
import os
import time
from typing import Any

BRAND = "#2f6feb"

# Curated personal-developer wall entries. Extended via PR — see README.
# Keep these as *people / homelab projects*, not enterprise logos: the
# strategy explicitly wants "個人開發者 wall", not a LiteLLM-style logo wall.
WALL_ENTRIES: list[dict[str, str]] = [
    {
        "label": "kiddhsu5",
        "detail": "homelab · Mac + Surface + Aliyun ECS · MiniMax / GLM / MiMo / Ollama",
        "url": "https://github.com/kiddhsu5",
    },
]


def api_payload(
    *,
    pools: list[dict[str, Any]],
    bot: dict[str, Any],
    cache: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    wall: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """JSON shape for ``/api/dashboard``. Secrets stay redacted upstream."""
    return {
        "generated_at": time.time(),
        "pools": pools,
        "bot": bot,
        "cache": cache or {"age_s": None, "warming": False},
        "history": history or [],
        "wall": wall if wall is not None else WALL_ENTRIES,
    }


def _css() -> str:
    return f"""
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
         margin: 0 auto; max-width: 64rem; padding: 1.75rem 1.25rem 4rem;
         line-height: 1.55; }}
  h1 {{ font-size: 1.55rem; margin-bottom: .15rem; }}
  h1 span {{ color: {BRAND}; }}
  h2 {{ font-size: 1.05rem; margin: 2rem 0 .75rem; }}
  .sub {{ opacity: .75; margin-top: 0; }}
  .badges {{ display: flex; gap: .5rem; flex-wrap: wrap; margin: 1rem 0 1.5rem; }}
  .badge {{ border: 1px solid color-mix(in srgb, {BRAND} 45%, transparent);
            color: {BRAND}; border-radius: 999px; padding: .22rem .7rem;
            font-size: .78rem; font-weight: 600; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
  th, td {{ text-align: left; padding: .45rem .55rem;
            border-bottom: 1px solid color-mix(in srgb, currentColor 14%, transparent);
            vertical-align: top; }}
  th {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .04em;
        opacity: .65; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: .85em; }}
  .small {{ font-size: .78rem; opacity: .8; }}
  .detail {{ max-width: 24rem; word-break: break-word; }}
  .summary {{ margin: 1rem 0 1.25rem; font-size: 1.02rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
            gap: .75rem; margin: 1rem 0 1.25rem; }}
  .card {{ border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
           border-radius: 10px; padding: .85rem 1rem; }}
  .card .n {{ font-size: 1.45rem; font-weight: 700; color: {BRAND}; }}
  .card .l {{ font-size: .78rem; opacity: .7; }}
  .wall {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
           gap: .75rem; margin: .75rem 0 1rem; }}
  .wall a {{ text-decoration: none; color: inherit; }}
  .wall .who {{ font-weight: 650; color: {BRAND}; }}
  footer {{ margin-top: 2.25rem; font-size: .78rem; opacity: .6; }}
  a {{ color: {BRAND}; }}
"""


def render_dashboard_html(
    *,
    pools: list[dict[str, Any]],
    bot: dict[str, Any],
    cache: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    wall: list[dict[str, str]] | None = None,
) -> str:
    ok_n = sum(1 for r in pools if r.get("ok") is True)
    warming_n = sum(1 for r in pools if r.get("ok") is None)
    total = len(pools)
    bot_ok = bool(bot.get("ok"))
    history = history or []
    wall = wall if wall is not None else WALL_ENTRIES

    def pool_row(r: dict[str, Any]) -> str:
        mark = "🟢" if r.get("ok") is True else ("🟡" if r.get("ok") is None else "🔴")
        caps = ", ".join(str(c) for c in (r.get("capabilities") or []))
        models = ", ".join(str(m) for m in (r.get("models") or []))
        return (
            "<tr>"
            f"<td>{mark}</td>"
            f"<td><code>{html.escape(str(r.get('name')))}</code></td>"
            f"<td>{html.escape(str(r.get('provider_id')))}</td>"
            f"<td class='small'>{html.escape(models)}</td>"
            f"<td class='small'>{html.escape(caps)}</td>"
            f"<td class='small detail'>{html.escape(str(r.get('detail') or ''))}</td>"
            "</tr>"
        )

    def hist_row(h: dict[str, Any]) -> str:
        ok = h.get("ok")
        mark = "✅" if ok else ("⏳" if ok is None else "❌")
        prompt = str(h.get("prompt") or h.get("phase") or "")[:80]
        backend = h.get("backend") or h.get("phase") or "-"
        ms = h.get("latency_ms")
        ts = h.get("ts")
        when = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "—"
        return (
            "<tr>"
            f"<td>{mark}</td>"
            f"<td class='small'>{html.escape(when)}</td>"
            f"<td><code>{html.escape(str(backend))}</code></td>"
            f"<td class='detail'>{html.escape(prompt)}</td>"
            f"<td class='small'>{ms if ms is not None else ''}</td>"
            "</tr>"
        )

    def wall_card(w: dict[str, str]) -> str:
        url = html.escape(w.get("url") or "#")
        label = html.escape(w.get("label") or "anonymous")
        detail = html.escape(w.get("detail") or "")
        return f"<a class='card' href='{url}' target='_blank' rel='noopener'><div class='who'>{label}</div><div class='small'>{detail}</div></a>"

    hist_rows = "\n".join(hist_row(h) for h in history[:25]) or (
        "<tr><td colspan='5' class='small'>尚無派工紀錄</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>K.H.A.V.I.S. · dashboard</title>
<style>{_css()}</style>
</head>
<body>
  <h1><span>K.H.A.V.I.S.</span> · dashboard</h1>
  <p class="sub">Operator view — pool health, bot phases, recent dispatches, personal-developer wall.</p>

  <div class="badges">
    <span class="badge">Apache 2.0</span>
    <span class="badge">Free forever</span>
    <span class="badge">Zero markup</span>
    <span class="badge">Self-hosted BYOK</span>
  </div>

  <div class="cards">
    <div class="card"><div class="n">{ok_n}/{total}</div><div class="l">pools healthy</div></div>
    <div class="card"><div class="n">{warming_n}</div><div class="l">warming up</div></div>
    <div class="card"><div class="n">{'OK' if bot_ok else 'DOWN'}</div><div class="l">telegram bot</div></div>
    <div class="card"><div class="n">{len(history)}</div><div class="l">recent events</div></div>
  </div>

  <p class="summary">
    {'🟢' if bot_ok else '🔴'} <strong>Telegram dispatch bot</strong> — {html.escape(str(bot.get('detail') or ''))}
  </p>

  <h2>LLM pools</h2>
  <table>
    <thead><tr><th></th><th>Pool</th><th>Provider</th><th>Models</th><th>Capabilities</th><th>Detail</th></tr></thead>
    <tbody>
      {''.join(pool_row(r) for r in pools)}
    </tbody>
  </table>

  <h2>Recent dispatches / phases</h2>
  <table>
    <thead><tr><th></th><th>Time</th><th>Backend</th><th>Prompt / phase</th><th>ms</th></tr></thead>
    <tbody>
      {hist_rows}
    </tbody>
  </table>

  <h2>個人開發者 wall</h2>
  <p class="small">In production at — personal / homelab setups, not enterprise logos.</p>
  <div class="wall">
    {''.join(wall_card(w) for w in wall)}
  </div>

  <footer>
    K.H.A.V.I.S. · free forever · <a href="/healthz">healthz</a> ·
    <a href="/">status</a> · <a href="/api/dashboard">api</a>
  </footer>
</body>
</html>
"""


def render_wall_html(wall: list[dict[str, str]] | None = None) -> str:
    wall = wall if wall is not None else WALL_ENTRIES

    def card(w: dict[str, str]) -> str:
        url = html.escape(w.get("url") or "#")
        label = html.escape(w.get("label") or "anonymous")
        detail = html.escape(w.get("detail") or "")
        return f"<a class='card' href='{url}' target='_blank' rel='noopener'><div class='who'>{label}</div><div class='small'>{detail}</div></a>"

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>K.H.A.V.I.S. · 個人開發者 wall</title>
<style>{_css()}</style>
</head>
<body>
  <h1><span>K.H.A.V.I.S.</span> · 個人開發者 wall</h1>
  <p class="sub">In production at personal / homelab setups. Open a PR to join.</p>
  <div class="wall">
    {''.join(card(w) for w in wall)}
  </div>
  <footer>K.H.A.V.I.S. · <a href="/dashboard">dashboard</a></footer>
</body>
</html>
"""


def default_history_dir() -> str:
    return os.environ.get("KHAVIS_LOG_DIR", "logs")
