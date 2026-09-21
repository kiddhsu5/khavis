"""Centralised environment loading for llm-router.

Loads variables from the project-root ``.env`` file exactly once per
process, with explicit process-env precedence (existing values are kept;
``.env`` only fills gaps). Idempotent — safe to call from any entry point.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_loaded: bool = False


def _project_root() -> Path:
    # core/ is at <project>/core/, so .env lives one level up.
    return Path(__file__).resolve().parent.parent


def load_env(file_path: Path | str | None = None, *, override: bool = False) -> bool:
    """Load ``.env`` into ``os.environ``.

    Returns ``True`` if a ``.env`` file was found and loaded, ``False``
    otherwise. Subsequent calls are no-ops unless ``force=True`` is
    passed via the module-level helper.
    """
    global _loaded
    if _loaded:
        return False
    path = Path(file_path) if file_path else _project_root() / ".env"
    if not path.exists():
        _loaded = True  # mark loaded even when missing so we don't keep looking
        return False
    load_dotenv(dotenv_path=path, override=override)
    _loaded = True
    return True


# NOTE: deliberately NOT calling ``load_env()`` here. Auto-loading on import
# would pollute test environments (tests that pass ``api_key=None`` to a
# plugin would silently inherit the real key from ``.env``). Callers that
# need .env (start.sh, integration_test.py, ...) must invoke
# ``load_env()`` explicitly.
