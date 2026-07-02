"""Per-child persistent memory: progress, preferences, anti-repetition ledger.

Model-agnostic by design — memory state is keyed by child_id, not by which
model answered a given turn, so swapping the model transport (self-hosted
Qwen 12B vs. Qwen Cloud API vs. anything else) never resets what Emma
remembers about a child.

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


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS child_memory (
            child_id TEXT PRIMARY KEY,
            preferences TEXT NOT NULL DEFAULT '{}',
            covered_topics TEXT NOT NULL DEFAULT '[]',
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
    covered_topics: list[str] = field(default_factory=list)
    praise_log: list[str] = field(default_factory=list)

    def has_covered(self, topic: str) -> bool:
        return topic.lower() in {t.lower() for t in self.covered_topics}

    def already_praised(self, achievement: str) -> bool:
        return achievement.lower() in {p.lower() for p in self.praise_log}


def load(child_id: str) -> ChildMemory:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT preferences, covered_topics, praise_log FROM child_memory WHERE child_id = ?",
            (child_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return ChildMemory(child_id=child_id)

    preferences, covered_topics, praise_log = row
    return ChildMemory(
        child_id=child_id,
        preferences=json.loads(preferences),
        covered_topics=json.loads(covered_topics),
        praise_log=json.loads(praise_log),
    )


def save(memory: ChildMemory) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO child_memory (child_id, preferences, covered_topics, praise_log, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(child_id) DO UPDATE SET
                preferences = excluded.preferences,
                covered_topics = excluded.covered_topics,
                praise_log = excluded.praise_log,
                updated_at = excluded.updated_at
            """,
            (
                memory.child_id,
                json.dumps(memory.preferences),
                json.dumps(memory.covered_topics),
                json.dumps(memory.praise_log),
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_topic_covered(child_id: str, topic: str) -> ChildMemory:
    memory = load(child_id)
    if not memory.has_covered(topic):
        memory.covered_topics.append(topic)
    save(memory)
    return memory


def record_praise(child_id: str, achievement: str) -> ChildMemory:
    memory = load(child_id)
    if not memory.already_praised(achievement):
        memory.praise_log.append(achievement)
    save(memory)
    return memory
