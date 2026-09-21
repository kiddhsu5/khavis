"""Role definitions for the multi-agent team.

Roles are configurable via ``config/agents.yaml`` so behaviour can be tuned
without touching code. Each :class:`Role` carries the minimum metadata
needed for the :mod:`agents.agent_factory` to materialise a LangChain
runnable for that persona.

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

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ----------------------------------------------------------------------
# Built-in fallbacks used when config/agents.yaml is missing entries.
# These mirror the YAML defaults shipped with the project.
# ----------------------------------------------------------------------
_BUILTIN: Dict[str, Dict[str, Any]] = {
    "planner": {
        "name": "planner",
        "display_name": "Planner",
        "system_prompt": (
            "你是 Planner。請把任務拆解成清楚的子步驟，輸出 markdown 編號清單。"
            "不要寫程式碼，只規劃。"
        ),
        "capability_required": "推理",
        "temperature": 0.2,
        "max_tokens": 1024,
        "max_iterations": 1,
        "style_hint": "",
    },
    "coder_a": {
        "name": "coder_a",
        "display_name": "CoderA",
        "system_prompt": (
            "你是 CoderA。風格：乾淨、可讀、易於維護。"
            "請依 plan 撰寫 Python 程式碼並回傳完整 source code block。"
        ),
        "capability_required": "程式碼",
        "temperature": 0.3,
        "max_tokens": 2048,
        "max_iterations": 1,
        "style_hint": "clean code",
    },
    "coder_b": {
        "name": "coder_b",
        "display_name": "CoderB",
        "system_prompt": (
            "你是 CoderB。風格：防禦、型別註解、邊界處理。"
            "請依 plan 撰寫 Python 程式碼並回傳完整 source code block。"
        ),
        "capability_required": "程式碼",
        "temperature": 0.3,
        "max_tokens": 2048,
        "max_iterations": 1,
        "style_hint": "defensive code",
    },
    "debater": {
        "name": "debater",
        "display_name": "Debater",
        "system_prompt": (
            "你是 Debater。請中立主持 A/B 兩個版本差異，列點比較優缺點。"
            "輸出一段結構化辯論紀錄。"
        ),
        "capability_required": "辯論",
        "temperature": 0.4,
        "max_tokens": 1024,
        "max_iterations": 2,
        "style_hint": "neutral",
    },
    "critic": {
        "name": "critic",
        "display_name": "Critic",
        "system_prompt": (
            "你是 Critic。請以銳利眼光審查最終方案的安全性、效能、可維護性，"
            "列出具體 issue 與建議。"
        ),
        "capability_required": "審查",
        "temperature": 0.2,
        "max_tokens": 1024,
        "max_iterations": 1,
        "style_hint": "sharp",
    },
    "verifier": {
        "name": "verifier",
        "display_name": "Verifier",
        "system_prompt": (
            "你是 Verifier。請獨立驗證結果是否通過需求，輸出 JSON："
            "{\"passed\": bool, \"issues\": [...], \"suggestions\": [...]}。"
        ),
        "capability_required": "驗證",
        "temperature": 0.1,
        "max_tokens": 1024,
        "max_iterations": 1,
        "style_hint": "reliable",
    },
    "learner": {
        "name": "learner",
        "display_name": "Learner",
        "system_prompt": (
            "你是 Learner。從本次 session 抽取可重用 pattern，"
            "提供給 router 學習。"
        ),
        "capability_required": "推理",
        "temperature": 0.2,
        "max_tokens": 512,
        "max_iterations": 1,
        "style_hint": "",
    },
}


@dataclass
class Role:
    """A single role/persona in the multi-agent team."""

    name: str
    display_name: str
    system_prompt: str
    capability_required: str
    temperature: float = 0.3
    max_tokens: int = 1024
    max_iterations: int = 1
    style_hint: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Role":
        return cls(
            name=str(data["name"]),
            display_name=str(data.get("display_name", data["name"])),
            system_prompt=str(data.get("system_prompt", "")),
            capability_required=str(data.get("capability_required", "推理")),
            temperature=float(data.get("temperature", 0.3)),
            max_tokens=int(data.get("max_tokens", 1024)),
            max_iterations=int(data.get("max_iterations", 1)),
            style_hint=str(data.get("style_hint", "")),
            extra={k: v for k, v in data.items() if k not in _ROLE_KEYS},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "system_prompt": self.system_prompt,
            "capability_required": self.capability_required,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_iterations": self.max_iterations,
            "style_hint": self.style_hint,
            **({"extra": dict(self.extra)} if self.extra else {}),
        }


_ROLE_KEYS = {
    "name",
    "display_name",
    "system_prompt",
    "capability_required",
    "temperature",
    "max_tokens",
    "max_iterations",
    "style_hint",
}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def _default_config_path() -> Path:
    """Return path to the shipped YAML config."""
    return Path(__file__).resolve().parent.parent / "config" / "agents.yaml"


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("roles") or {}


def load_role(name: str, config_path: Optional[Path] = None) -> Role:
    """Load a role by name. Falls back to built-in defaults."""
    yaml_roles = _load_yaml(Path(config_path) if config_path else _default_config_path())
    data = yaml_roles.get(name) or _BUILTIN.get(name)
    if data is None:
        raise KeyError(f"unknown role: {name!r}")
    return Role.from_dict(data)


def list_roles(config_path: Optional[Path] = None) -> List[str]:
    """Return all known role names (built-in + configured)."""
    yaml_roles = _load_yaml(Path(config_path) if config_path else _default_config_path())
    seen = set(_BUILTIN.keys())
    seen.update(yaml_roles.keys())
    return sorted(seen)


def create_role(name: str, **kwargs: Any) -> Role:
    """Construct a role in code, optionally overriding fields."""
    base = _BUILTIN.get(name)
    if base is None:
        base = {
            "name": name,
            "display_name": name,
            "system_prompt": "",
            "capability_required": "推理",
        }
    merged = {**base, **kwargs, "name": name}
    return Role.from_dict(merged)


__all__ = ["Role", "load_role", "list_roles", "create_role"]