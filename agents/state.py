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

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph import add_messages


def _last_wins(existing: Any, new: Any) -> Any:
    """Reducer that keeps the most recent value.

    LangGraph's default for ``Optional[str]``-shaped keys raises
    ``InvalidUpdateError`` when two nodes write to the same key in one
    step. Since every node in this graph already produces a final value
    (rather than incrementally building one), last-write-wins is the
    correct merge.
    """
    return new


def _append_list(existing: Any, new: Any) -> Any:
    """Reducer that appends to a list."""
    return (list(existing) if existing else []) + (list(new) if new else [])


class TeamState(TypedDict, total=False):
    """Shared state object that flows through every node in the team graph.

    Every mutable key carries an explicit ``Annotated[...]`` reducer so
    that LangGraph never raises ``InvalidUpdateError`` when two nodes
    write to the same key in one step (planner → fallback sets the same
    field that the happy path also sets, debate node appends to the
    debate log, etc.).
    """

    # ---- inputs (immutable per step) ----
    task: Annotated[str, _last_wins]
    session_id: Annotated[str, _last_wins]

    # ---- intermediate artefacts (last write wins) ----
    plan: Annotated[Optional[str], _last_wins]
    code_a: Annotated[Optional[str], _last_wins]
    code_b: Annotated[Optional[str], _last_wins]
    debate_log: Annotated[List[Dict[str, Any]], _append_list]
    critic_review: Annotated[Optional[str], _last_wins]
    verification: Annotated[Optional[Dict[str, Any]], _last_wins]

    # ---- output (last write wins) ----
    final: Annotated[Optional[str], _last_wins]

    # ---- meta ----
    attribution: Annotated[Dict[str, Any], _last_wins]
    error: Annotated[Optional[str], _last_wins]
    rounds: Annotated[int, _last_wins]
    fallback_used: Annotated[bool, _last_wins]


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