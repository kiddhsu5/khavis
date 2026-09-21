"""Learning node — captures successful patterns into memory.

After verification passes, this node:

* appends an episode to :class:`EpisodicMemory`,
* pushes a short summary into :class:`SemanticMemory`,
* logs attribution for the learner agent.

Router weights are intentionally NOT mutated here — the capability router
remains declarative. The learning node only stores observations for
later offline tuning.

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
from ..memory import (
    get_working_memory,
    recall_similar,
    semantic_search,
    store_episode,
)
from ..roles import load_role
from ..state import TeamState, add_attribution, log_step

log = logging.getLogger(__name__)


def learn_node(state: TeamState) -> TeamState:
    """Persist successful patterns and update working memory."""
    session_id = state.get("session_id", "default")
    task = state.get("task", "")
    verification = state.get("verification") or {}
    if not verification.get("passed"):
        # Only learn from successful runs.
        add_attribution(state, agent="learner", node="learn", skipped=True)
        return state

    role = load_role("learner")
    factory = get_agent_factory()
    agent = factory.create_agent(role)

    # Pull related past episodes to ground the learning prompt.
    related = recall_similar("task:" + task[:64], limit=3)
    related_semantic = semantic_search(task, k=3) if hasattr(semantic_search, "__call__") else []
    history_lines = [
        f"- #{r['id']}: {str(r['value'])[:120]}" for r in related
    ] or ["(no prior episodes)"]

    messages = [
        {"role": "system", "content": role.system_prompt},
        {
            "role": "user",
            "content": (
                f"Task:\n{task}\n\n"
                f"Verification:\n{verification}\n\n"
                f"Past similar episodes:\n" + "\n".join(history_lines) +
                "\n\n請輸出 1-2 句可重用 pattern。"
            ),
        },
    ]

    try:
        summary = agent.invoke(
            messages,
            temperature=role.temperature,
            max_tokens=role.max_tokens,
        )
        store_episode(
            key="task:" + task[:64],
            value={
                "task": task,
                "summary": summary,
                "verification": verification,
                "session_id": session_id,
            },
        )
        get_working_memory().set(f"learned:{session_id}", summary)
        log_step(state, node="learn", summary_chars=len(summary))
        add_attribution(state, agent="learner", node="learn", learned_chars=len(summary))
        get_attribution_logger().log_decision(
            session_id=session_id,
            agent="learner",
            node="learn",
            pool=agent.pool.name,
            decision="learned",
            metadata={"related_episodes": len(related)},
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("learn node failed")
        state["fallback_used"] = True
        add_attribution(state, agent="learner", node="learn", error=str(exc))
    return state


__all__ = ["learn_node"]