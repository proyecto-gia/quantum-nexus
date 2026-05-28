"""Command Center — Estado global consolidado del ecosistema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandCenter:
    state: dict[str, Any] = field(default_factory=dict)

    def update(self, key: str, value: Any) -> None:
        self.state[key] = value

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state)
