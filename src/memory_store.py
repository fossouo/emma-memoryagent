"""Per-child persistent memory: structured learning state, not chat history.

Model-agnostic by design — memory state is keyed by child_id, not by which
model answered a given turn, so swapping the model transport (self-hosted
Qwen 12B vs. Qwen Cloud API vs. anything else) never resets what Emma
remembers about a child.

Each topic is stored as a small record (status, first_seen, last_seen), not
a bare string, so Emma can reason about mastery progression over time and
bound what gets sent into the model's context window each turn (see
`top_k_topics` — used by src/main.py to implement "recall critical memories
within limited context windows" rather than dumping the full history).

Minimal SQLite-backed implementation for the hackathon build. A production
deployment would use DynamoDB (as Talki's main Emma product does), but
SQLite keeps this repo dependency-free and easy for judges to run locally.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "memory.sqlite3"

STATUS_PROGRESSION = ["started", "practicing", "mastered"]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS child_memory (
            child_id TEXT PRIMARY KEY,
            preferences TEXT NOT NULL DEFAULT '{}',
            topics TEXT NOT NULL DEFAULT '{}',
            praise_log TEXT NOT NULL DEFAULT '[]',
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


@dataclass
class ChildMemory:
    child_id: str
    preferences: dict = field(default_factory=dict)
    topics: dict = field(default_factory=dict)  # topic -> {status, first_seen, last_seen}
    praise_log: list[str] = field(default_factory=list)

    def has_covered(self, topic: str) -> bool:
        return topic.lower() in {t.lower() for t in self.topics}

    def already_praised(self, achievement: str) -> bool:
        return achievement.lower() in {p.lower() for p in self.praise_log}

    def most_recent_topic(self) -> str | None:
        if not self.topics:
            return None
        return max(self.topics, key=lambda t: self.topics[t]["last_seen"])

    def top_k_topics(self, k: int = 3) -> list[str]:
        """Bounded recall: the k most recently-touched topics, not the full log.

        This is the "limited context window" behavior — only these get
        formatted into the model's system prompt (see src/main.py).
        """
        return sorted(self.topics, key=lambda t: self.topics[t]["last_seen"], reverse=True)[:k]


def load(child_id: str) -> ChildMemory:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT preferences, topics, praise_log FROM child_memory WHERE child_id = ?",
            (child_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return ChildMemory(child_id=child_id)

    preferences, topics, praise_log = row
    return ChildMemory(
        child_id=child_id,
        preferences=json.loads(preferences),
        topics=json.loads(topics),
        praise_log=json.loads(praise_log),
    )


def save(memory: ChildMemory) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO child_memory (child_id, preferences, topics, praise_log, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(child_id) DO UPDATE SET
                preferences = excluded.preferences,
                topics = excluded.topics,
                praise_log = excluded.praise_log,
                updated_at = excluded.updated_at
            """,
            (
                memory.child_id,
                json.dumps(memory.preferences),
                json.dumps(memory.topics),
                json.dumps(memory.praise_log),
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_topic_covered(
    child_id: str,
    topic: str,
    skill: str | None = None,
    support_style: str | None = None,
) -> ChildMemory:
    """Write or update structured learning state for a topic.

    First time: status="started". Each subsequent turn on the same topic
    advances status one step (started -> practicing -> mastered) — this is
    the "memory update over time" behavior, not just an append-only log.

    skill/support_style capture *how* this child is being taught the topic
    (e.g. skill="adding same-denominator fractions",
    support_style="hints_not_answers" for homework help that guides instead
    of giving the answer away) — this is what makes the stored state a
    learning profile, not just a topic tag.
    """
    memory = load(child_id)
    now = time.time()
    key = topic.lower()
    existing = memory.topics.get(key)
    if existing is None:
        memory.topics[key] = {
            "status": "started",
            "first_seen": now,
            "last_seen": now,
            "skill": skill,
            "support_style": support_style,
        }
    else:
        idx = STATUS_PROGRESSION.index(existing["status"])
        new_status = STATUS_PROGRESSION[min(idx + 1, len(STATUS_PROGRESSION) - 1)]
        memory.topics[key] = {
            **existing,
            "status": new_status,
            "last_seen": now,
            "skill": skill or existing.get("skill"),
            "support_style": support_style or existing.get("support_style"),
        }
    save(memory)
    return memory


def record_praise(child_id: str, achievement: str) -> ChildMemory:
    memory = load(child_id)
    if not memory.already_praised(achievement):
        memory.praise_log.append(achievement)
    save(memory)
    return memory
