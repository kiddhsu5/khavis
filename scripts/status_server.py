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
import concurrent.futures
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


# (rows, monotonic timestamp). Served stale and refreshed in the
# background once older than CACHE_TTL.
CACHE_TTL = 30.0
_HEALTH_CACHE: tuple[list[dict[str, object]] | None, float] = (None, 0.0)
_CACHE_LOCK = threading.Lock()
_REFRESHING = False
_PLUG_CACHE: list | None = None  # registry snapshot; see _load_plugins()
WARMING_DETAIL = "warming up — first sweep in progress"


def cache_state() -> dict[str, object]:
    """How stale is what we are about to serve? Surfaced on ``/healthz``.

    Operators staring at a 522-shaped problem need to tell "the router is
    down" apart from "you are looking at placeholder rows".
    """
    rows, cached_at = _HEALTH_CACHE
    with _CACHE_LOCK:
        warming = _REFRESHING or rows is None
    return {
        "age_s": None if rows is None else round(time.monotonic() - cached_at, 3),
        "warming": warming,
    }


def pool_health() -> list[dict[str, object]]:
    """Return one row per registered pool. Never raises, and never blocks.

    Stale-while-revalidate. A sweep costs as long as the slowest
    unreachable endpoint (a home-LAN Ollama burns its whole connect
    timeout — ~20s here), so a TTL-expiry must never land on a visitor.

    The cold path must not block either, which is the whole point of this
    function. Cloudflare gives up on an origin after ~15s and answers 522,
    so a first request that waits out a 20s sweep turns *everyone* who
    loads the page right after a restart into a 522 — including the
    uptime check that would otherwise tell us the service is fine. Serve
    placeholder rows immediately and let the sweep fill them in.
    """
    global _HEALTH_CACHE  # noqa: PLW0603 - module-level memo is intended

    rows, cached_at = _HEALTH_CACHE
    if rows is not None:
        if (time.monotonic() - cached_at) >= CACHE_TTL:
            _kick_refresh()
        return rows

    _kick_refresh()
    return _placeholder_rows()


def _placeholder_rows() -> list[dict[str, object]]:
    """Rows for a sweep that has not landed yet. ``ok`` is None, not False.

    None keeps the page honest: the pools are not down, we simply have not
    looked yet. ``False`` would light the summary red and make an operator
    chase a phantom outage.
    """
    try:
        plugs = _load_plugins()
    except Exception as exc:  # noqa: BLE001 - placeholder must not raise
        return [{
            "name": "registry",
            "provider_id": "",
            "models": [],
            "capabilities": [],
            "ok": None,
            "detail": _redact(f"warming up ({type(exc).__name__})"),
        }]
    return [
        {
            "name": getattr(p, "name", "?"),
            "provider_id": getattr(p, "provider_id", ""),
            "models": list(getattr(p, "models", None) or ([p.model] if getattr(p, "model", None) else [])),
            "capabilities": list(getattr(p, "capabilities", None) or []),
            "ok": None,
            "detail": WARMING_DETAIL,
        }
        for p in plugs
    ]


def _kick_refresh() -> None:
    """Start one background resweep. No-op if one is already running."""
    global _REFRESHING  # noqa: PLW0603 - module-level flag is intended

    with _CACHE_LOCK:
        if _REFRESHING:
            return
        _REFRESHING = True

    def run() -> None:
        global _REFRESHING, _HEALTH_CACHE  # noqa: PLW0603
        try:
            _HEALTH_CACHE = (_probe_all_pools(), time.monotonic())
        except Exception as exc:  # noqa: BLE001 - never kill the refresher
            print(f"health refresh failed: {exc!r}", file=sys.stderr, flush=True)
        finally:
            with _CACHE_LOCK:
                _REFRESHING = False

    threading.Thread(target=run, daemon=True, name="khavis-health-refresh").start()


def warm_cache() -> None:
    """Fill the cache before anyone asks. Failures must not stop startup."""
    try:
        _kick_refresh()
    except Exception as exc:  # noqa: BLE001 - warm-up is best-effort
        print(f"warm-up failed: {exc!r}", file=sys.stderr, flush=True)


def _load_plugins() -> list:
    """Discover the registry once and memo the plugin objects.

    Separated from ``_probe_all_pools`` so the cold path can name the pools
    without paying for their health probes. Discovery is sub-millisecond and
    the YAML parse is single-digit milliseconds — cheap enough for a request
    — but we memo anyway because this runs behind every placeholder render.
    """
    global _PLUG_CACHE  # noqa: PLW0603 - module-level memo is intended

    if _PLUG_CACHE is not None:
        return _PLUG_CACHE

    from core.registry import PluginRegistry  # noqa: PLC0415 - lazy

    reg = PluginRegistry(PROJECT_ROOT).discover()
    reg.apply_pools_config(PROJECT_ROOT / "config" / "pools.yaml")
    _PLUG_CACHE = list(reg.all())
    return _PLUG_CACHE


def _probe_all_pools() -> list[dict[str, object]]:
    try:
        plugs = _load_plugins()
    except Exception as exc:  # noqa: BLE001
        return [{"name": "registry", "ok": False, "detail": _redact(f"import failed: {exc!r}"), "models": [], "capabilities": [], "provider_id": ""}]
    return _probe_plugins(plugs)


def _probe_plugins(plugs: list) -> list[dict[str, object]]:
    """Run every plugin's health_check concurrently.

    Wall time should track the slowest probe, not the sum of all of them.
    """

    def probe(plug) -> dict[str, object]:  # noqa: ANN001 - plugin type is ProviderPlugin
        try:
            h = plug.health_check()
            ok = bool(h.get("ok"))
            detail = str(h.get("detail", ""))
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        return {
            "name": plug.name,
            "provider_id": plug.provider_id,
            "models": list(plug.list_models()),
            "capabilities": list(plug.capabilities),
            "ok": ok,
            "detail": _redact(detail),
        }

    if not plugs:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(plugs)) as pool:
        return list(pool.map(probe, plugs))


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


def render_html(
    rows: list[dict[str, object]],
    bot: dict[str, object],
    cache: dict[str, object] | None = None,
) -> str:
    # ``ok is True`` rather than truthiness: a warming row is ``None`` and
    # must not be counted as either healthy or down.
    ok_n = sum(1 for r in rows if r.get("ok") is True)
    warming_n = sum(1 for r in rows if r.get("ok") is None)
    total = len(rows)
    bot_ok = bool(bot.get("ok"))
    cache = cache or {"age_s": None, "warming": False}

    def row_html(r: dict[str, object]) -> str:
        mark = "🟢" if r.get("ok") is True else ("🟡" if r.get("ok") is None else "🔴")
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
    {'<br>🟡 <strong>' + str(warming_n) + ' warming up</strong> — first sweep still running, refresh in a moment' if warming_n else ''}
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
      · cache age {'n/a' if cache.get('age_s') is None else str(cache.get('age_s')) + 's'}{' · refreshing' if cache.get('warming') else ''}
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
        if path not in ("/", "/healthz"):
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        rows = pool_health()
        bot = bot_health()
        if path == "/healthz":
            cache = cache_state()
            payload = {
                # None rows are "not looked at yet", not "down" — do not
                # fold them into ok, or a warm-up looks like an outage.
                "ok": all(r.get("ok") is True for r in rows) and bool(bot.get("ok")),
                "cache": cache,
                "bot": bot,
                "pools": rows,
                "generated_at": time.strftime(GENERATED_AT_FORMAT, time.gmtime()),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        self._send(200, render_html(rows, bot, cache_state()).encode(), "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def resolve_cert_paths(cert_path: Path, key_path: Path) -> tuple[Path, Path]:
    """Prefer the requested location; fall back to a temp dir if it is not creatable.

    Under systemd the unit declares ``CacheDirectory=khavis-status`` so the
    directory already exists and is writable. A bare manual run may not have
    that, and ``ProtectSystem=``-style lockdown is not the only reason a
    ``/etc/...`` default would fail to create — so degrade instead of dying.
    """
    try:
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        return cert_path, key_path
    except OSError as exc:
        import tempfile  # noqa: PLC0415 - only on the fallback path

        fallback = Path(tempfile.mkdtemp(prefix="khavis-status-"))
        print(
            f"cert dir {cert_path.parent} not usable ({exc!r}); using {fallback}",
            file=sys.stderr,
            flush=True,
        )
        return fallback / cert_path.name, fallback / key_path.name


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


def primary_ipv4() -> str | None:
    """Outbound IPv4 of this host, without touching DNS.

    A UDP ``connect()`` picks a local address from the routing table and
    sends no packets. Deliberately not ``getaddrinfo(gethostname())`` —
    on a host with a ``.local`` name that blocks on mDNS for seconds and
    would stall service startup.
    """
    import socket  # noqa: PLC0415 - only needed here

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        addr = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if not addr or addr.startswith("127.") else addr


def candidate_hosts(preferred: str) -> list[str]:
    """Bind addresses to try, most preferred first.

    A wildcard bind conflicts with *any* socket already holding that port
    on a specific address. On this box ``tailscaled`` holds 443 on the
    Tailscale IP, so ``0.0.0.0:443`` is EADDRINUSE even though the public
    path is completely free — falling back to a concrete unicast address
    sidesteps the clash without disturbing whatever else is running.
    """
    hosts = [preferred]
    if preferred not in ("0.0.0.0", "::", ""):
        return hosts
    addr = primary_ipv4()
    if addr is not None and addr not in hosts:
        hosts.append(addr)
    hosts.append("127.0.0.1")
    return hosts


class _TLSServer(ThreadingHTTPServer):
    """HTTPS server that wraps each *accepted* socket.

    The shorter-looking alternative —

        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    — wraps the *listening* socket and is a trap. The assignment drops the
    only reference to the original socket object, whose ``__del__`` closes
    the shared file descriptor, so the listener vanishes shortly after the
    "listening on ..." line is printed and every later connection is
    refused. What is left behind is a socket that still shows up in
    ``ss -ltn`` with a growing ``Recv-Q`` until the GC runs. Wrap per
    connection instead; the handshake then happens in the handler thread
    and a slow client cannot stall accept.
    """

    def __init__(self, addr: tuple[str, int], handler, ctx: ssl.SSLContext) -> None:
        self._ctx = ctx
        super().__init__(addr, handler)

    def get_request(self):  # noqa: ANN201 - matches socketserver's signature
        conn, addr = super().get_request()
        # Cap the handshake so half-open TLS attempts cannot pin threads.
        conn.settimeout(10)
        try:
            conn = self._ctx.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            conn.close()
            # socketserver treats OSError from get_request as "skip this
            # connection", which is what we want for scanners sending
            # plain HTTP to the HTTPS port. A real error would otherwise
            # spam a traceback per probe.
            raise OSError(f"TLS handshake failed from {addr[0]}: {exc}") from exc
        finally:
            try:
                conn.settimeout(None)
            except OSError:  # pragma: no cover - socket already gone
                pass
        return conn, addr


def start_listener(
    label: str,
    host: str,
    port: int,
    wrap_ssl: ssl.SSLContext | None = None,
) -> tuple[str, ThreadingHTTPServer, threading.Thread] | None:
    """Bind one listener, trying ``candidate_hosts`` in order.

    Returns None when nothing bound — a dead :443 must not take :80 down
    with it, and vice versa.
    """
    errors: list[str] = []
    for addr in candidate_hosts(host):
        try:
            srv: ThreadingHTTPServer
            if wrap_ssl is not None:
                srv = _TLSServer((addr, port), Handler, wrap_ssl)
            else:
                srv = ThreadingHTTPServer((addr, port), Handler)
        except OSError as exc:
            errors.append(f"{addr}:{port} -> {exc.strerror or exc}")
            continue
        note = " (self-signed)" if wrap_ssl is not None else ""
        print(f"khavis-status listening on {label}://{addr}:{port}{note}", flush=True)
        return (f"{label}://{addr}", srv, threading.Thread(target=srv.serve_forever, daemon=True))
    print(f"khavis-status: could not bind {label}:{port} — {'; '.join(errors)}", file=sys.stderr, flush=True)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="khavis-status")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80, help="plain HTTP (Cloudflare SSL mode Flexible)")
    parser.add_argument("--tls-port", type=int, default=443, help="HTTPS with self-signed cert (Cloudflare SSL mode Full)")
    parser.add_argument("--cert", type=Path, default=Path("/var/cache/khavis-status/cert.pem"))
    parser.add_argument("--key", type=Path, default=Path("/var/cache/khavis-status/key.pem"))
    args = parser.parse_args()
    cert_path, key_path = resolve_cert_paths(args.cert, args.key)

    started: list[tuple[str, ThreadingHTTPServer, threading.Thread]] = []

    http = start_listener("http", args.host, args.port)
    if http is not None:
        started.append(http)

    if args.tls_port:
        if ensure_self_signed_cert(cert_path, key_path):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert_path), str(key_path))
            https = start_listener("https", args.host, args.tls_port, wrap_ssl=ctx)
            if https is not None:
                started.append(https)

    if not started:
        raise SystemExit("khavis-status: no listener could be bound; refusing to idle")

    for _name, _srv, t in started:
        t.start()
    # Fill the health cache before the first visitor arrives. Without this
    # the very first request pays for the sweep; see pool_health().
    warm_cache()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        for _name, srv, _t in started:
            srv.shutdown()


if __name__ == "__main__":
    main()
