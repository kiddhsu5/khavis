#!/usr/bin/env python3
"""Daemonize the llm-router Telegram dispatch bot.

Launches the bot via a POSIX double-fork so it survives the launching
shell's exit. Mirrors what ``nohup`` does on macOS without depending on
``setsid`` (which doesn't ship by default).

The resulting child writes its PID to ``--pid-file`` and its logs to
``--log-file``. Both paths default to ``/tmp/bot.{pid,log}`` so this
script works without arguments. A second invocation kills the
existing PID before re-launching — safe to re-run.

Usage:
    python scripts/launch_bot_daemon.py                    # use defaults
    python scripts/launch_bot_daemon.py --help
    python scripts/launch_bot_daemon.py --stop             # kill + exit

After launch:
    tail -f /tmp/bot.log
    python scripts/launch_bot_daemon.py --stop             # tear down
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_PYTHON = "/opt/homebrew/bin/python3.12"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PID_FILE = Path("/tmp/bot.pid")
DEFAULT_LOG_FILE = Path("/tmp/bot.log")


def _kill_existing(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        old = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(old, 9)
        print(f"[launcher] killed stale pid {old}", file=sys.stderr)
    except ProcessLookupError:
        pass
    pid_file.unlink(missing_ok=True)


def _first_fork() -> None:
    if os.fork() > 0:
        os._exit(0)


def _second_fork() -> None:
    if os.fork() > 0:
        os._exit(0)


def launch(
    *,
    project_root: Path,
    python_bin: str,
    pid_file: Path,
    log_file: Path,
    mode: str,
) -> Path:
    """Daemonise the bot. Returns the PID of the daemon process."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    _kill_existing(pid_file)

    # Round 1: detach from controlling tty.
    _first_fork()
    os.setsid()
    # Round 2: ensure the daemon can never reacquire a tty.
    _second_fork()

    # We are the daemon. Re-direct stdio to the log file.
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "rb", 0) as devnull:
        os.dup2(devnull.fileno(), 0)
    fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)

    pid_file.write_text(f"{os.getpid()}\n")
    print(f"[launcher] bot daemon pid={os.getpid()}", flush=True)

    # Load the project .env into the daemon's environment.
    env_file = project_root / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()
    else:
        print(f"[launcher] WARNING: {env_file} not found; bot will exit", flush=True)
        os._exit(1)

    os.chdir(str(project_root))
    os.execv(
        python_bin,
        [python_bin, "-B", "-u", "-m", "bot.main", "--mode", mode],
    )
    # execv does not return on success.
    raise RuntimeError("execv returned; daemon failed to start")  # pragma: no cover


def stop(pid_file: Path) -> None:
    if not pid_file.exists():
        print("[launcher] no pid file; nothing to stop")
        return
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, 15)  # SIGTERM
        print(f"[launcher] sent SIGTERM to pid {pid}")
    except ProcessLookupError:
        print(f"[launcher] pid {pid} not running")
    pid_file.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project-root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Path to the llm-router checkout (default: %(default)s)",
    )
    parser.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help="Python interpreter to use (default: %(default)s)",
    )
    parser.add_argument(
        "--pid-file",
        type=Path,
        default=DEFAULT_PID_FILE,
        help="Where the daemon writes its PID (default: %(default)s)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help="Where the daemon writes stdout/stderr (default: %(default)s)",
    )
    parser.add_argument(
        "--mode",
        choices=("polling", "webhook"),
        default=os.environ.get("BOT_MODE", "polling"),
        help="Bot listen mode",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Send SIGTERM to the running daemon and exit",
    )
    args = parser.parse_args()
    if args.stop:
        stop(args.pid_file)
        return 0
    launch(
        project_root=args.project_root,
        python_bin=args.python,
        pid_file=args.pid_file,
        log_file=args.log_file,
        mode=args.mode,
    )
    return 0  # unreachable in practice; the parent already exited


if __name__ == "__main__":
    raise SystemExit(main())
