"""Verifier node — independent cross-pool validation.

The verifier uses a *different* pool than the coder/debater pool to
catch blind spots. It returns a dict shaped like::

    {"passed": bool, "issues": [...], "suggestions": [...]}

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ..agent_factory import get_agent_factory
from ..attribution import get_attribution_logger
from ..roles import load_role
from ..state import TeamState, add_attribution, log_step

log = logging.getLogger(__name__)


VERIFY_PASS = "pass"
VERIFY_RETRY = "retry"


def _parse_payload(content: str) -> Dict[str, Any]:
    """Best-effort parse of the verifier's JSON output."""
    if not content:
        return {"passed": False, "issues": ["empty response"], "suggestions": []}
    # Try to locate a JSON block.
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {
        "passed": False,
        "issues": ["could not parse verifier output"],
        "suggestions": [content[:512]],
        "raw": content,
    }


def _select_alt_pool(factory, role, primary_name: str):
    """Pick a different pool than ``primary_name`` for cross-validation."""
    candidates = factory.router.candidates(role.capability_required)
    for plugin in candidates:
        if plugin.name != primary_name:
            return plugin
    return None


def verify_node(state: TeamState) -> TeamState:
    """Produce ``state['verification']`` and decide pass/retry."""
    session_id = state.get("session_id", "default")
    task = state.get("task", "")
    code_a = state.get("code_a") or ""
    code_b = state.get("code_b") or ""
    review = state.get("critic_review") or ""

    role = load_role("verifier")
    factory = get_agent_factory()
    primary = factory.create_agent(role)

    # Cross-validation: try a different pool if available.
    alt = _select_alt_pool(factory, role, primary.pool.name)
    chosen = primary
    pool_used = primary.pool.name
    if alt is not None:
        try:
            chosen = factory.create_agent(role, pool_name=alt.name)
            pool_used = alt.name
        except Exception:
            chosen = primary
            pool_used = primary.pool.name

    messages = [
        {"role": "system", "content": role.system_prompt},
        {
            "role": "user",
            "content": (
                f"Original task:\n{task}\n\n"
                f"Code A:\n{code_a}\n\n"
                f"Code B:\n{code_b}\n\n"
                f"Critic review:\n{review}\n\n"
                "請獨立驗證並以 JSON 格式回答。"
            ),
        },
    ]
    try:
        content = chosen.invoke(
            messages,
            temperature=role.temperature,
            max_tokens=role.max_tokens,
        )
        payload = _parse_payload(content)
        state["verification"] = payload
        log_step(state, node="verifier", passed=bool(payload.get("passed")))
        get_attribution_logger().log_decision(
            session_id=session_id,
            agent="verifier",
            node="verifier",
            pool=pool_used,
            decision="pass" if payload.get("passed") else "retry",
        )
        state["__verify_route__"] = (
            VERIFY_PASS if payload.get("passed") else VERIFY_RETRY
        )
        # Set final to the winning code so downstream nodes can read it.
        if payload.get("passed"):
            state["final"] = (
                "# Verified solution\n\n"
                f"## Code A\n```python\n{code_a}\n```\n\n"
                f"## Code B\n```python\n{code_b}\n```\n\n"
                f"## Review\n{review}\n"
            )
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("verifier failed")
        state["error"] = f"verifier: {exc!r}"
        state["fallback_used"] = True
        state["verification"] = {
            "passed": False,
            "issues": [f"verifier error: {exc!r}"],
            "suggestions": [],
        }
        state["__verify_route__"] = VERIFY_RETRY
        add_attribution(state, agent="verifier", node="verifier", error=str(exc))
    return state


def route_after_verify(state: TeamState) -> str:
    """Conditional edge used by :func:`agents.graph.build_graph`."""
    route = state.get("__verify_route__") or VERIFY_RETRY
    return route if route in {VERIFY_PASS, VERIFY_RETRY} else VERIFY_RETRY


__all__ = [
    "verify_node",
    "route_after_verify",
    "VERIFY_PASS",
    "VERIFY_RETRY",
]