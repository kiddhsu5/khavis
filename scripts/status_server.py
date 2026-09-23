#!/usr/bin/env python3
"""Public status page for ``khavis.kiddhsu.taipei``.

A tiny stdlib-only HTTP server that renders live pool health. Serves
``/`` (HTML) and ``/healthz`` (JSON). Nothing else — no auth, no write
paths, no admin surface. It is a billboard, not a control panel.

Run with the project venv so ``core.registry`` imports resolve::

    /root/llm-router-bot/.venv/bin/python -m scripts.status_server --port 80

Cloudflare terminates TLS at the edge; the origin serves plain HTTP on
``:80`` *and* HTTPS with a throwaway self-signed cert on ``:443``. Both
on purpose: ``bot.kiddhsu.taipei`` already shares this zone, so we must
not force a zone-wide SSL-mode change. Serving both ports means the
record works whether the zone (or a per-hostname Configuration Rule) is
set to ``Flexible`` (edge -> :80) or ``Full`` (edge -> :443; Cloudflare
accepts a self-signed origin cert outside strict mode).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BRAND = "#0EA5E9"  # sky-500 — the project's single accent colour
GENERATED_AT_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

# This page is public. health_check() reports ``key_present=`` and raw
# exception text, and exceptions can embed request headers — so scrub
# anything credential-shaped before it is rendered or serialised.
_SECRET_PATTERNS = (
    re.compile(r"\bkey_present=\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S{6,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),
)


def _redact(text: str) -> str:
    """Strip credential-shaped substrings from a public-facing string."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[redacted]", text)
    return text


def pool_health() -> list[dict[str, object]]:
    """Return one row per registered pool. Never raises."""
    try:
        from core.registry import PluginRegistry  # noqa: PLC0415 - lazy
    except Exception as exc:  # noqa: BLE001
        return [{"name": "registry", "ok": False, "detail": _redact(f"import failed: {exc!r}"), "models": [], "capabilities": [], "provider_id": ""}]

    try:
        reg = PluginRegistry(PROJECT_ROOT).discover()
        try:
            reg.apply_pools_config(PROJECT_ROOT / "config" / "pools.yaml")
        except Exception as exc:  # noqa: BLE001
            reg_rows: list[dict[str, object]] = [{"name": "pools.yaml", "ok": False, "detail": _redact(repr(exc)), "models": [], "capabilities": [], "provider_id": ""}]
            return reg_rows
    except Exception as exc:  # noqa: BLE001
        return [{"name": "registry", "ok": False, "detail": _redact(f"discover failed: {exc!r}"), "models": [], "capabilities": [], "provider_id": ""}]

    rows: list[dict[str, object]] = []
    for plug in reg.all():
        try:
            h = plug.health_check()
            ok = bool(h.get("ok"))
            detail = str(h.get("detail", ""))
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "name": plug.name,
                "provider_id": plug.provider_id,
                "models": list(plug.list_models()),
                "capabilities": list(plug.capabilities),
                "ok": ok,
                "detail": _redact(detail),
            }
        )
    return rows


def bot_health() -> dict[str, object]:
    """Is the Telegram dispatch bot process alive on this box?"""
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["systemctl", "is-active", "llm-router-bot"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": _redact(repr(exc))}
    return {"ok": out == "active", "detail": f"systemd llm-router-bot: {out or 'unknown'}"}


def render_html(rows: list[dict[str, object]], bot: dict[str, object]) -> str:
    ok_n = sum(1 for r in rows if r.get("ok"))
    total = len(rows)
    bot_ok = bool(bot.get("ok"))

    def row_html(r: dict[str, object]) -> str:
        mark = "🟢" if r.get("ok") else "🔴"
        caps = ", ".join(str(c) for c in r.get("capabilities", []))  # type: ignore[arg-type]
        models = ", ".join(str(m) for m in r.get("models", []))  # type: ignore[arg-type]
        return (
            "<tr>"
            f"<td>{mark}</td>"
            f"<td><code>{html.escape(str(r.get('name')))}</code></td>"
            f"<td>{html.escape(str(r.get('provider_id')))}</td>"
            f"<td class='small'>{html.escape(models)}</td>"
            f"<td class='small'>{html.escape(caps)}</td>"
            f"<td class='small detail'>{html.escape(str(r.get('detail')))}</td>"
            "</tr>"
        )

    body_rows = "\n".join(row_html(r) for r in rows)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>khavis · llm-router status</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
         margin: 0 auto; max-width: 62rem; padding: 2rem 1.25rem 4rem;
         line-height: 1.55; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .2rem; }}
  h1 span {{ color: {BRAND}; }}
  .sub {{ opacity: .75; margin-top: 0; }}
  .badges {{ display: flex; gap: .5rem; flex-wrap: wrap; margin: 1.25rem 0 1.75rem; }}
  .badge {{ border: 1px solid color-mix(in srgb, {BRAND} 45%, transparent);
            color: {BRAND}; border-radius: 999px; padding: .25rem .7rem;
            font-size: .8rem; font-weight: 600; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
  th, td {{ text-align: left; padding: .5rem .55rem;
            border-bottom: 1px solid color-mix(in srgb, currentColor 14%, transparent);
            vertical-align: top; }}
  th {{ font-size: .75rem; text-transform: uppercase; letter-spacing: .04em;
        opacity: .65; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: .85em; }}
  .small {{ font-size: .78rem; opacity: .8; }}
  .detail {{ max-width: 22rem; word-break: break-word; }}
  .summary {{ margin: 1rem 0 1.5rem; font-size: 1.05rem; }}
  footer {{ margin-top: 2.5rem; font-size: .78rem; opacity: .6; }}
  a {{ color: {BRAND}; }}
</style>
</head>
<body>
  <h1><span>khavis</span> · llm-router</h1>
  <p class="sub">Unified interface for 12 LLM pools with smart routing and zero quota interruption.</p>

  <div class="badges">
    <span class="badge">Apache 2.0</span>
    <span class="badge">Free forever</span>
    <span class="badge">Zero markup</span>
    <span class="badge">Self-hosted BYOK</span>
  </div>

  <p class="summary">
    {'🟢' if bot_ok else '🔴'} <strong>Telegram dispatch bot</strong> — {html.escape(str(bot.get('detail')))}
    <br>
    {'🟢' if ok_n == total and total else '🟡'} <strong>{ok_n} / {total}</strong> LLM pools healthy
  </p>

  <table>
    <thead>
      <tr><th></th><th>Pool</th><th>Provider</th><th>Models</th><th>Capabilities</th><th>Detail</th></tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>

  <footer>
    <p>
      <a href="https://github.com/kiddhsu5/llm-router">github.com/kiddhsu5/llm-router</a>
      · <a href="/healthz">/healthz</a>
      · rendered {time.strftime(GENERATED_AT_FORMAT, time.gmtime())}
    </p>
  </footer>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "khavis-status/1.0"

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        rows = pool_health()
        bot = bot_health()
        if path == "/healthz":
            payload = {
                "ok": all(bool(r.get("ok")) for r in rows) and bool(bot.get("ok")),
                "bot": bot,
                "pools": rows,
                "generated_at": time.strftime(GENERATED_AT_FORMAT, time.gmtime()),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        if path == "/":
            self._send(200, render_html(rows, bot).encode(), "text/html; charset=utf-8")
            return
        self._send(404, b'{"error":"not found"}', "application/json")

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def ensure_self_signed_cert(cert_path: Path, key_path: Path) -> bool:
    """Create a throwaway self-signed cert if neither file exists yet.

    Returns True when a cert is available. The private key never leaves
    the box and is worthless to an attacker who already has root on it —
    its only job is to satisfy Cloudflare outside ``Full (strict)``.
    """
    if cert_path.exists() and key_path.exists():
        return True
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-days", "825",
        "-keyout", str(key_path), "-out", str(cert_path),
        "-subj", "/CN=khavis.kiddhsu.taipei",
        "-addext", "subjectAltName=DNS:khavis.kiddhsu.taipei,DNS:localhost",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cert bootstrap failed: {exc!r}", file=sys.stderr, flush=True)
        return False
    key_path.chmod(0o600)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="khavis-status")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80, help="plain HTTP (Cloudflare SSL mode Flexible)")
    parser.add_argument("--tls-port", type=int, default=443, help="HTTPS with self-signed cert (Cloudflare SSL mode Full)")
    parser.add_argument("--cert", type=Path, default=Path("/etc/khavis-status/cert.pem"))
    parser.add_argument("--key", type=Path, default=Path("/etc/khavis-status/key.pem"))
    args = parser.parse_args()

    servers: list[tuple[str, ThreadingHTTPServer, threading.Thread]] = []

    http_srv = ThreadingHTTPServer((args.host, args.port), Handler)
    servers.append(("http", http_srv, threading.Thread(target=http_srv.serve_forever, daemon=True)))
    print(f"khavis-status listening on http://{args.host}:{args.port}", flush=True)

    if args.tls_port and ensure_self_signed_cert(args.cert, args.key):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(args.cert), str(args.key))
        https_srv = ThreadingHTTPServer((args.host, args.tls_port), Handler)
        https_srv.socket = ctx.wrap_socket(https_srv.socket, server_side=True)
        servers.append(("https", https_srv, threading.Thread(target=https_srv.serve_forever, daemon=True)))
        print(f"khavis-status listening on https://{args.host}:{args.tls_port} (self-signed)", flush=True)

    for _name, _srv, t in servers:
        t.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        for _name, srv, _t in servers:
            srv.shutdown()


if __name__ == "__main__":
    main()
