"""Unit tests for the multi-agent graph.

These tests cover:

* role loading,
* state helper behaviour,
* node execution with mocked agents,
* routing decisions,
* fallback behaviour.

They intentionally avoid touching the network — every test injects a
fake agent factory so the LLM call is replaced by a deterministic
function.

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

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest  # noqa: E402

from agents import roles as roles_mod  # noqa: E402
from agents import state as state_mod  # noqa: E402
from agents.agent_factory import AgentFactory, set_agent_factory  # noqa: E402
from agents.nodes import (  # noqa: E402
    coder_a_node,
    coder_b_node,
    critic_node,
    debate_node,
    learn_node,
    planner_node,
    verify_node,
)
from agents.nodes.debate import (  # noqa: E402
    DEBATE_CONTINUE,
    DEBATE_ESCALATE,
    route_after_debate,
)
from agents.nodes.verifier import (  # noqa: E402
    VERIFY_PASS,
    VERIFY_RETRY,
    route_after_verify,
)


# ----------------------------------------------------------------------
# Fake agent factory
# ----------------------------------------------------------------------
class FakeRunnable:
    def __init__(self, pool, role, answer, fail=False):
        self.pool = pool
        self.role = role
        self.answer = answer
        self.fail = fail

    def invoke(self, messages, **kwargs):  # noqa: D401
        if self.fail:
            raise RuntimeError("simulated failure")
        return self.answer


class FakePool:
    def __init__(self, name="fake-pool"):
        self.name = name
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": "ok"}}]}


class FakeFactory(AgentFactory):
    def __init__(self, answers=None, fail_for=None):
        # Skip real registry / router init.
        self.registry = type(
            "R",
            (),
            {"get": lambda self, n: FakePool(n), "by_capability": lambda self, c: [FakePool()]},
        )()
        self.router = type(
            "Router",
            (),
            {
                "candidates": lambda self, c: [FakePool()],
                "select": lambda self, c: FakePool("selected"),
            },
        )()
        self.answers = answers or {}
        self.fail_for = fail_for or set()
        self._cache = {}

    def create_agent(self, role, pool_name=None):
        cache_key = (role.name, pool_name or "default")
        if cache_key in self._cache:
            return self._cache[cache_key]
        if role.name in self.fail_for:
            r = FakeRunnable(FakePool(), role, "", fail=True)
        else:
            answer = self.answers.get(role.name, f"answer-for-{role.name}")
            r = FakeRunnable(FakePool(), role, answer)
        self._cache[cache_key] = r
        return r

    def _resolve(self, pool_name):
        return FakePool(pool_name) if pool_name else FakePool()


@pytest.fixture(autouse=True)
def install_fake_factory():
    set_agent_factory(FakeFactory())
    yield
    set_agent_factory(None)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# State helpers
# ----------------------------------------------------------------------
def test_state_helpers():
    s: state_mod.TeamState = {"task": "x", "attribution": {}}
    state_mod.add_attribution(s, agent="planner", note="first")
    assert s["attribution"]["records"][0]["agent"] == "planner"
    state_mod.log_step(s, node="planner", produced=3)
    assert any(r.get("node") == "planner" for r in s["attribution"]["records"])


# ----------------------------------------------------------------------
# Roles
# ----------------------------------------------------------------------
def test_role_loading():
    planner = roles_mod.load_role("planner")
    assert planner.name == "planner"
    assert planner.capability_required
    assert "planner" in roles_mod.list_roles()


def test_create_role_overrides():
    custom = roles_mod.create_role(
        "planner",
        temperature=0.9,
        system_prompt="custom",
    )
    assert custom.temperature == 0.9
    assert custom.system_prompt == "custom"


# ----------------------------------------------------------------------
# Nodes
# ----------------------------------------------------------------------
def test_planner_node_populates_plan():
    s: state_mod.TeamState = {"task": "do X", "attribution": {"records": []}}
    out = planner_node(s)
    assert "plan" in out and out["plan"]


def test_coder_nodes_run_in_parallel():
    plan_state: state_mod.TeamState = {
        "task": "t",
        "plan": "step 1\nstep 2",
        "attribution": {"records": []},
    }
    a = coder_a_node(dict(plan_state))
    b = coder_b_node(dict(plan_state))
    assert a.get("code_a") and b.get("code_b")


def test_debate_node_routing_continue_then_escalate():
    s: state_mod.TeamState = {
        "task": "t",
        "plan": "p",
        "code_a": "A",
        "code_b": "B",
        "debate_log": [],
        "attribution": {"records": []},
        "rounds": 0,
    }
    first = debate_node(dict(s))
    assert first["__route__"] in {DEBATE_CONTINUE, DEBATE_ESCALATE}
    assert first["rounds"] == 1
    assert first["debate_log"]
    assert route_after_debate(first) == first["__route__"]

    # Force continuation past max_iterations.
    forced: state_mod.TeamState = {
        **first,
        "rounds": 99,
    }
    next_round = debate_node(dict(forced))
    assert next_round["__route__"] == DEBATE_ESCALATE


def test_critic_node_records_review():
    s: state_mod.TeamState = {
        "task": "t",
        "plan": "p",
        "code_a": "A",
        "code_b": "B",
        "critic_review": None,
        "attribution": {"records": []},
    }
    out = critic_node(s)
    assert out.get("critic_review")


def test_verify_node_routes_pass_and_retry():
    # Set FakeFactory answers to JSON that should pass.
    set_agent_factory(
        FakeFactory(answers={"verifier": '{"passed": true, "issues": [], "suggestions": []}'})
    )
    s: state_mod.TeamState = {
        "task": "t",
        "code_a": "A",
        "code_b": "B",
        "critic_review": "ok",
        "attribution": {"records": []},
    }
    out = verify_node(s)
    assert out["__verify_route__"] == VERIFY_PASS
    assert out["verification"]["passed"] is True

    # Now force a failing payload.
    set_agent_factory(
        FakeFactory(answers={"verifier": '{"passed": false, "issues": ["x"], "suggestions": []}'})
    )
    out2 = verify_node(
        {
            "task": "t",
            "code_a": "A",
            "code_b": "B",
            "critic_review": "ok",
            "attribution": {"records": []},
        }
    )
    assert out2["__verify_route__"] == VERIFY_RETRY
    assert out2["verification"]["passed"] is False
    assert route_after_verify(out2) == VERIFY_RETRY


def test_verify_node_fallback_when_factory_fails():
    set_agent_factory(FakeFactory(fail_for={"verifier"}))
    s: state_mod.TeamState = {
        "task": "t",
        "code_a": "A",
        "code_b": "B",
        "critic_review": "ok",
        "attribution": {"records": []},
    }
    out = verify_node(s)
    assert out["fallback_used"] is True
    assert out["verification"]["passed"] is False
    assert out["__verify_route__"] == VERIFY_RETRY


def test_learn_node_no_op_on_failure():
    s: state_mod.TeamState = {
        "task": "t",
        "verification": {"passed": False},
        "attribution": {"records": []},
    }
    out = learn_node(s)
    # When verification failed we should still see the agent record.
    agents = [r.get("agent") for r in out["attribution"]["records"]]
    assert "learner" in agents


def test_learn_node_persists_on_success():
    s: state_mod.TeamState = {
        "task": "task-xyz",
        "verification": {"passed": True, "issues": [], "suggestions": []},
        "attribution": {"records": []},
    }
    out = learn_node(s)
    # At least one attribution record should mention the learner.
    assert any(r.get("agent") == "learner" for r in out["attribution"]["records"])


# ----------------------------------------------------------------------
# Graph assembly (skipped if langgraph not installed)
# ----------------------------------------------------------------------
def test_build_graph_returns_compiled():
    try:
        import langgraph  # noqa: F401  # probe only
    except ImportError:
        pytest.skip("langgraph not installed")
    from agents.graph import build_graph

    g = build_graph()
    assert g is not None
    # Compiled graphs expose ``invoke`` and ``stream``.
    assert hasattr(g, "invoke")
    assert hasattr(g, "stream")
