"""Coder A / Coder B nodes — produce two distinct implementations.

Both nodes share the same skeleton; the difference is purely the role
configuration (``style_hint`` and ``system_prompt``). They run in
parallel after :func:`planner_node` so the team can compare approaches.

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

import logging
from typing import Any, Dict

from ..agent_factory import get_agent_factory
from ..attribution import get_attribution_logger
from ..roles import load_role
from ..state import TeamState, add_attribution, log_step

log = logging.getLogger(__name__)


def _produce_code(state: TeamState, role_name: str, output_key: str) -> TeamState:
    plan = state.get("plan")
    task = state.get("task", "")
    session_id = state.get("session_id", "default")
    if not plan:
        state[output_key] = state.get(output_key) or f"# {role_name}: no plan available"
        add_attribution(state, agent=role_name, node=role_name, error="no plan")
        return state

    role = load_role(role_name)
    factory = get_agent_factory()
    agent = factory.create_agent(role)

    user_msg = (
        f"Plan:\n{plan}\n\n"
        f"Original task:\n{task}\n\n"
        f"Style hint: {role.style_hint}\n\n"
        "請回傳完整 Python source code (含 ```python 區塊)。"
    )
    messages = [
        {"role": "system", "content": role.system_prompt},
        {"role": "user", "content": user_msg},
    ]
    try:
        code = agent.invoke(
            messages,
            temperature=role.temperature,
            max_tokens=role.max_tokens,
        )
        state[output_key] = code
        log_step(state, node=role_name, produced_chars=len(code))
        get_attribution_logger().log_decision(
            session_id=session_id,
            agent=role_name,
            node=role_name,
            pool=agent.pool.name,
            decision="coded",
            metadata={"style": role.style_hint},
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("%s failed", role_name)
        state["error"] = f"{role_name}: {exc!r}"
        state["fallback_used"] = True
        state[output_key] = state.get(output_key) or "# generation failed; placeholder"
        add_attribution(state, agent=role_name, node=role_name, error=str(exc))
    return state


def coder_a_node(state: TeamState) -> TeamState:
    """Coder A: clean / readable implementation."""
    return _produce_code(state, "coder_a", "code_a")


def coder_b_node(state: TeamState) -> TeamState:
    """Coder B: defensive / typed implementation."""
    return _produce_code(state, "coder_b", "code_b")


__all__ = ["coder_a_node", "coder_b_node"]