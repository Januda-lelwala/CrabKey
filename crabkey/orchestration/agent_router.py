from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..mal.provider import ModelConfig, ModelProvider
from ..persistence.config import AgentConfig


@dataclass
class Agent:
    name: str
    provider: ModelProvider
    config: ModelConfig
    tools: list[str] = field(default_factory=list)  # tool names this agent can use


class AgentRouter:
    """
    Maps agent names to Agent instances.
    Sub-agents are just agents invoked with an isolated context window.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError:
            raise KeyError(f"Unknown agent: {name!r}")

    def from_config(self, cfg: AgentConfig, provider: ModelProvider) -> Agent:
        model_config = ModelConfig(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=cfg.system,
        )
        agent = Agent(name=cfg.name, provider=provider, config=model_config, tools=cfg.tools)
        self.register(agent)
        return agent

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())
