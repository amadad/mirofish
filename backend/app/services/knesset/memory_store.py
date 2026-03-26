"""KnessetMemoryStore — SQLite-based persistent memory for simulation agents.

Provides episodic memory, relationship tracking, and voting pattern analysis
for Knesset MK agents across simulation rounds. Implements the memory_store
interface expected by KnessetLoop (save / get).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("mirofish.knesset.memory_store")

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "../../../data/knesset/agent_memory.db"
)

# ---------------------------------------------------------------------------
# Action-type → Hebrew memory text templates
# ---------------------------------------------------------------------------

_ACTION_TEMPLATES: dict[str, str] = {
    "VOTE": "הצבעתי {vote_value} על {bill_id}. נימוק: {reasoning}",
    "SPEAK_IN_PLENUM": "נאמתי: {speech_text}",
    "SPEAK": "נאמתי: {speech_text}",
    "LOBBY": "שכנעתי את {target_mk_id}: {reasoning}",
    "FORM_ALLIANCE": "הקמתי ברית עם {target_mk_id}",
    "DEFECT": "עזבתי את הסיעה/הקואליציה",
    "PROPOSE_BILL": "הצעתי חוק: {bill_id}",
    "AMEND_BILL": "הצעתי תיקון ל-{bill_id}",
}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    simulation_id TEXT,
    timestamp TEXT NOT NULL,
    platform TEXT DEFAULT 'plenum',
    topic_he TEXT,
    outcome TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    episode_id TEXT,
    memory_type TEXT NOT NULL,
    content_he TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    round_num INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (episode_id) REFERENCES episodes(episode_id)
);

CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_episode ON memories(episode_id);

CREATE TABLE IF NOT EXISTS agent_relationships (
    agent_a TEXT NOT NULL,
    agent_b TEXT NOT NULL,
    relationship_type TEXT DEFAULT 'neutral',
    strength REAL DEFAULT 0.5,
    episode_count INTEGER DEFAULT 1,
    last_updated TEXT NOT NULL,
    PRIMARY KEY (agent_a, agent_b)
);

CREATE TABLE IF NOT EXISTS voting_patterns (
    agent_id TEXT NOT NULL,
    category TEXT NOT NULL,
    votes_for INTEGER DEFAULT 0,
    votes_against INTEGER DEFAULT 0,
    votes_abstain INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, category)
);
"""


class KnessetMemoryStore:
    """SQLite-backed persistent memory store for Knesset simulation agents.

    Thread-safe: creates a new connection per method call.
    Uses WAL journal mode for concurrent read/write performance.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()
        self._current_episode_id: Optional[str] = None
        logger.info("KnessetMemoryStore initialised at %s", self.db_path)

    # -- internal helpers ---------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Return a new WAL-mode connection."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- public API ---------------------------------------------------------

    def start_episode(
        self,
        simulation_id: str,
        topic_he: str,
        platform: str = "plenum",
    ) -> str:
        """Create a new episode record and return its id."""
        episode_id = f"ep-{uuid.uuid4().hex[:12]}"
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO episodes (episode_id, simulation_id, timestamp, platform, topic_he) "
                "VALUES (?, ?, ?, ?, ?)",
                (episode_id, simulation_id, self._now(), platform, topic_he),
            )
            conn.commit()
        finally:
            conn.close()
        self._current_episode_id = episode_id
        logger.debug("Started episode %s for sim %s", episode_id, simulation_id)
        return episode_id

    def save(self, agent_id: str, round_num: int, action_dict: dict) -> None:
        """Persist an agent action as a Hebrew-text memory.

        This is the interface KnessetLoop calls after each round.
        """
        action_type = action_dict.get("action_type", "")
        template = _ACTION_TEMPLATES.get(action_type)

        if template is None:
            content_he = f"{action_type}: {action_dict.get('reasoning', '')}"
        else:
            speech = action_dict.get("speech_text") or ""
            content_he = template.format(
                vote_value=action_dict.get("vote_value", ""),
                bill_id=action_dict.get("bill_id", ""),
                reasoning=action_dict.get("reasoning", ""),
                speech_text=speech[:100],
                target_mk_id=action_dict.get("target_mk_id", ""),
            )

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO memories "
                "(agent_id, episode_id, memory_type, content_he, strength, round_num, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    agent_id,
                    self._current_episode_id,
                    "action",
                    content_he,
                    1.0,
                    round_num,
                    json.dumps(action_dict, ensure_ascii=False),
                    self._now(),
                ),
            )
            # Update voting patterns when action is VOTE
            if action_type == "VOTE":
                self._record_vote(conn, agent_id, action_dict)
            conn.commit()
        finally:
            conn.close()

    def get(self, agent_id: str, limit: int = 10) -> str:
        """Return the most recent memories for an agent as formatted Hebrew text.

        This is the interface KnessetLoop reads during prompt building.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT content_he, strength FROM memories "
                "WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return ""

        lines = [
            f"- [חוזק {row['strength']:.0%}] {row['content_he']}" for row in rows
        ]
        return "\n".join(lines)

    def end_episode(self, episode_id: str, outcome: str) -> None:
        """Finalise an episode: record outcome, update relationships, decay."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE episodes SET outcome = ? WHERE episode_id = ?",
                (outcome, episode_id),
            )
            conn.commit()
        finally:
            conn.close()

        self.update_relationships(episode_id)
        self.decay_memories()
        logger.debug("Ended episode %s — outcome: %s", episode_id, outcome)

    def update_relationships(self, episode_id: str) -> None:
        """Strengthen/weaken agent relationships based on vote alignment."""
        conn = self._connect()
        try:
            # Collect votes in this episode grouped by bill
            rows = conn.execute(
                "SELECT agent_id, metadata_json FROM memories "
                "WHERE episode_id = ? AND memory_type = 'action'",
                (episode_id,),
            ).fetchall()

            # bill_id → {agent_id: vote_value}
            bill_votes: dict[str, dict[str, str]] = {}
            for row in rows:
                meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                if meta.get("action_type") != "VOTE":
                    continue
                bid = meta.get("bill_id", "")
                if not bid:
                    continue
                bill_votes.setdefault(bid, {})[row["agent_id"]] = meta.get("vote_value", "")

            now = self._now()
            for _bid, votes in bill_votes.items():
                agents = list(votes.keys())
                for i, a in enumerate(agents):
                    for b in agents[i + 1:]:
                        delta = 0.1 if votes[a] == votes[b] else -0.1
                        pair = tuple(sorted([a, b]))
                        cur = conn.execute(
                            "SELECT strength, episode_count FROM agent_relationships "
                            "WHERE agent_a = ? AND agent_b = ?",
                            pair,
                        ).fetchone()

                        if cur:
                            new_str = max(0.0, min(1.0, cur["strength"] + delta))
                            rtype = (
                                "ally" if new_str > 0.7
                                else "rival" if new_str < 0.3
                                else "neutral"
                            )
                            conn.execute(
                                "UPDATE agent_relationships "
                                "SET strength = ?, relationship_type = ?, episode_count = ?, last_updated = ? "
                                "WHERE agent_a = ? AND agent_b = ?",
                                (new_str, rtype, cur["episode_count"] + 1, now, *pair),
                            )
                        else:
                            new_str = max(0.0, min(1.0, 0.5 + delta))
                            rtype = (
                                "ally" if new_str > 0.7
                                else "rival" if new_str < 0.3
                                else "neutral"
                            )
                            conn.execute(
                                "INSERT INTO agent_relationships "
                                "(agent_a, agent_b, relationship_type, strength, episode_count, last_updated) "
                                "VALUES (?, ?, ?, ?, 1, ?)",
                                (*pair, rtype, new_str, now),
                            )
            conn.commit()
        finally:
            conn.close()

    def decay_memories(self, factor: float = 0.95) -> None:
        """Multiply all memory strengths by *factor*; prune weak ones."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE memories SET strength = strength * ?", (factor,)
            )
            conn.execute("DELETE FROM memories WHERE strength < 0.1")
            conn.commit()
        finally:
            conn.close()

    def get_relationship_summary(self, agent_id: str) -> str:
        """Return a Hebrew text summary of an agent's relationships."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT agent_a, agent_b, relationship_type FROM agent_relationships "
                "WHERE (agent_a = ? OR agent_b = ?) AND relationship_type != 'neutral'",
                (agent_id, agent_id),
            ).fetchall()
        finally:
            conn.close()

        allies: list[str] = []
        rivals: list[str] = []
        for row in rows:
            other = row["agent_b"] if row["agent_a"] == agent_id else row["agent_a"]
            if row["relationship_type"] == "ally":
                allies.append(other)
            elif row["relationship_type"] == "rival":
                rivals.append(other)

        parts: list[str] = []
        if allies:
            parts.append(f"בעלי ברית: {', '.join(allies)}")
        if rivals:
            parts.append(f"יריבים: {', '.join(rivals)}")
        return ". ".join(parts) + "." if parts else "אין קשרים בולטים."

    def get_voting_pattern(self, agent_id: str) -> str:
        """Return a Hebrew voting-pattern summary for an agent."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT category, votes_for, votes_against, votes_abstain "
                "FROM voting_patterns WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return "אין נתוני הצבעה."

        lines = [
            f"- {row['category']}: בעד {row['votes_for']}, נגד {row['votes_against']}, נמנע {row['votes_abstain']}"
            for row in rows
        ]
        return "\n".join(lines)

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _record_vote(conn: sqlite3.Connection, agent_id: str, action: dict) -> None:
        """Upsert a vote into the voting_patterns table."""
        category = action.get("bill_id", "general")
        vote = action.get("vote_value", "")
        col = (
            "votes_for" if vote == "בעד"
            else "votes_against" if vote == "נגד"
            else "votes_abstain"
        )
        conn.execute(
            f"INSERT INTO voting_patterns (agent_id, category, {col}) "
            f"VALUES (?, ?, 1) "
            f"ON CONFLICT(agent_id, category) DO UPDATE SET {col} = {col} + 1",
            (agent_id, category),
        )
