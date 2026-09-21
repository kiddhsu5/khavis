"""LangGraph TeamState definition and attribution helpers.

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

from typing import Any, Dict, List, Optional, TypedDict


class TeamState(TypedDict, total=False):
    """Shared state object that flows through every node in the team graph.

    Using ``TypedDict`` (not Pydantic BaseModel) keeps the state fully
    compatible with LangGraph's reducers and checkpointer machinery.
    """

    # ---- inputs ----
    task: str
    session_id: str

    # ---- intermediate artefacts ----
    plan: Optional[str]
    code_a: Optional[str]
    code_b: Optional[str]
    debate_log: List[Dict[str, Any]]
    critic_review: Optional[str]
    verification: Optional[Dict[str, Any]]

    # ---- output ----
    final: Optional[str]

    # ---- meta ----
    attribution: Dict[str, Any]
    error: Optional[str]
    rounds: int
    fallback_used: bool


def add_attribution(state: TeamState, **record: Any) -> TeamState:
    """Append an attribution record to ``state['attribution']``.

    Each record is keyed by the agent/role that produced it. The function
    creates the attribution dict when missing so callers don't have to
    initialise the state themselves.
    """
    attribution = dict(state.get("attribution") or {})
    bucket: List[Dict[str, Any]] = list(attribution.get("records", []))
    bucket.append(dict(record))
    attribution["records"] = bucket
    state["attribution"] = attribution
    return state


def log_step(state: TeamState, node: str, **payload: Any) -> TeamState:
    """Attach a generic step log entry to the attribution log."""
    return add_attribution(
        state,
        node=node,
        type="step",
        **payload,
    )


__all__ = ["TeamState", "add_attribution", "log_step"]