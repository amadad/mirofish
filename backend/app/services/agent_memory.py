"""Persistent agent memory across simulations.

Agents accumulate beliefs, relationships, and behavioral patterns
that persist between simulation runs. This creates emergent personality
development and more realistic long-term behavior.

Storage: JSON files per agent in uploads/agent_memory/<project_id>/
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.agent_memory")


@dataclass
class MemoryEntry:
    """A single memory — something the agent learned or experienced."""
    content: str
    source: str  # "action", "observation", "belief", "relationship"
    simulation_id: str = ""
    round_num: int = 0
    timestamp: str = ""
    strength: float = 1.0  # 0.0 to 1.0, decays over time
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentMemoryState:
    """Full persistent state for one agent."""
    agent_id: str
    agent_name: str
    role: str = ""
    personality: str = ""

    # Accumulated memories
    beliefs: List[MemoryEntry] = field(default_factory=list)
    relationships: List[MemoryEntry] = field(default_factory=list)
    actions_history: List[MemoryEntry] = field(default_factory=list)
    observations: List[MemoryEntry] = field(default_factory=list)

    # Behavioral stats
    total_simulations: int = 0
    total_actions: int = 0
    last_simulation_id: str = ""
    last_active: str = ""

    # Personality evolution
    stance_shifts: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "role": self.role,
            "personality": self.personality,
            "beliefs": [b.to_dict() for b in self.beliefs],
            "relationships": [r.to_dict() for r in self.relationships],
            "actions_history": [a.to_dict() for a in self.actions_history],
            "observations": [o.to_dict() for o in self.observations],
            "total_simulations": self.total_simulations,
            "total_actions": self.total_actions,
            "last_simulation_id": self.last_simulation_id,
            "last_active": self.last_active,
            "stance_shifts": self.stance_shifts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMemoryState":
        state = cls(
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            role=data.get("role", ""),
            personality=data.get("personality", ""),
            total_simulations=data.get("total_simulations", 0),
            total_actions=data.get("total_actions", 0),
            last_simulation_id=data.get("last_simulation_id", ""),
            last_active=data.get("last_active", ""),
            stance_shifts=data.get("stance_shifts", {}),
        )
        for key, mem_list_name in [
            ("beliefs", "beliefs"),
            ("relationships", "relationships"),
            ("actions_history", "actions_history"),
            ("observations", "observations"),
        ]:
            for entry_data in data.get(key, []):
                entry = MemoryEntry(**entry_data)
                getattr(state, mem_list_name).append(entry)
        return state

    def get_context_summary(self, max_entries: int = 10) -> str:
        """Generate a context string for agent prompts."""
        lines = []

        if self.total_simulations > 0:
            lines.append(f"[You have participated in {self.total_simulations} previous simulations]")

        # Top beliefs (sorted by strength)
        strong_beliefs = sorted(self.beliefs, key=lambda b: b.strength, reverse=True)[:max_entries]
        if strong_beliefs:
            lines.append("\nYour established beliefs:")
            for b in strong_beliefs:
                lines.append(f"  - {b.content} (confidence: {b.strength:.0%})")

        # Key relationships
        recent_rels = sorted(self.relationships, key=lambda r: r.strength, reverse=True)[:5]
        if recent_rels:
            lines.append("\nYour key relationships:")
            for r in recent_rels:
                lines.append(f"  - {r.content}")

        # Recent notable actions
        recent_actions = self.actions_history[-5:]
        if recent_actions:
            lines.append("\nYour recent notable actions:")
            for a in recent_actions:
                lines.append(f"  - {a.content}")

        return "\n".join(lines) if lines else ""


class AgentMemoryStore:
    """Manages persistent memory for all agents in a project.

    Usage:
        store = AgentMemoryStore("project_123")
        memory = store.load("agent_42")  # Load existing or create new
        memory.beliefs.append(MemoryEntry(content="Markets are bearish", source="observation"))
        store.save(memory)
    """

    def __init__(self, project_id: str, base_dir: Optional[str] = None):
        self.project_id = project_id
        self.base_dir = base_dir or os.path.join(
            os.path.dirname(__file__), "..", "uploads", "agent_memory"
        )
        self._dir = os.path.join(os.path.abspath(self.base_dir), project_id)
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, agent_id: str) -> str:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in agent_id)
        return os.path.join(self._dir, f"{safe_id}.json")

    def load(self, agent_id: str, agent_name: str = "", role: str = "") -> AgentMemoryState:
        """Load agent memory from disk, or create new if doesn't exist."""
        path = self._path(agent_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = AgentMemoryState.from_dict(data)
                logger.debug("Loaded memory for agent %s (%d beliefs)", agent_id, len(state.beliefs))
                return state
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to load memory for %s: %s", agent_id, e)

        return AgentMemoryState(
            agent_id=agent_id,
            agent_name=agent_name,
            role=role,
        )

    def save(self, state: AgentMemoryState) -> None:
        """Save agent memory to disk."""
        path = self._path(state.agent_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
        logger.debug("Saved memory for agent %s", state.agent_id)

    def save_simulation_results(
        self,
        simulation_id: str,
        agent_actions: List[Dict],
        decay_factor: float = 0.9,
    ) -> int:
        """Process simulation results and update agent memories.

        Args:
            simulation_id: ID of the completed simulation
            agent_actions: List of AgentAction dicts from the simulation
            decay_factor: How much old memories decay (0.9 = 10% weaker each sim)

        Returns:
            Number of agents updated
        """
        # Group actions by agent
        by_agent: Dict[str, List[Dict]] = {}
        for action in agent_actions:
            aid = action.get("agent_id", "")
            by_agent.setdefault(aid, []).append(action)

        updated = 0
        for agent_id, actions in by_agent.items():
            state = self.load(agent_id, agent_name=actions[0].get("agent_name", ""))

            # Decay existing memories
            for mem_list in [state.beliefs, state.relationships, state.observations]:
                for entry in mem_list:
                    entry.strength *= decay_factor
                # Remove very weak memories
                mem_list[:] = [e for e in mem_list if e.strength > 0.1]

            # Add new action memories
            for action in actions:
                action_type = action.get("action_type", "DO_NOTHING")
                if action_type == "DO_NOTHING":
                    continue

                content = action.get("action_args", {}).get("content", "")
                summary = f"{action_type}"
                if content:
                    summary += f": {content[:100]}"

                state.actions_history.append(MemoryEntry(
                    content=summary,
                    source="action",
                    simulation_id=simulation_id,
                    round_num=action.get("round_num", 0),
                    timestamp=action.get("timestamp", ""),
                    strength=1.0,
                ))

            # Keep actions history bounded
            if len(state.actions_history) > 50:
                state.actions_history = state.actions_history[-50:]

            state.total_simulations += 1
            state.total_actions += len(actions)
            state.last_simulation_id = simulation_id
            state.last_active = datetime.now(timezone.utc).isoformat()

            self.save(state)
            updated += 1

        logger.info(
            "Updated memory for %d agents from simulation %s",
            updated, simulation_id,
        )
        return updated

    def list_agents(self) -> List[str]:
        """List all agent IDs with saved memory."""
        if not os.path.exists(self._dir):
            return []
        return [
            f.replace(".json", "")
            for f in os.listdir(self._dir)
            if f.endswith(".json")
        ]

    def get_all_stats(self) -> Dict:
        """Get summary stats for all agents."""
        agents = self.list_agents()
        total_beliefs = 0
        total_sims = 0
        for aid in agents:
            state = self.load(aid)
            total_beliefs += len(state.beliefs)
            total_sims = max(total_sims, state.total_simulations)
        return {
            "total_agents": len(agents),
            "total_beliefs": total_beliefs,
            "max_simulations": total_sims,
            "project_id": self.project_id,
        }

    def clear(self) -> int:
        """Clear all agent memories for this project."""
        agents = self.list_agents()
        for aid in agents:
            path = self._path(aid)
            if os.path.exists(path):
                os.remove(path)
        logger.info("Cleared memory for %d agents in project %s", len(agents), self.project_id)
        return len(agents)
