"""Deterministic, pre-model compliance layer.

Runs BEFORE any request reaches the LLM. Model-location-agnostic: the same
checks apply whether the model behind it is a self-hosted local SLM or a
hosted API (Qwen Cloud, here). Mirrors the Agent Firewall pattern already
documented for Emma's E-API profile (talki-app docs/emma-lab).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Very small illustrative denylist — a real deployment would load this from
# a maintained policy pack, not hardcode it.
BLOCKED_TOPICS = (
    "self-harm",
    "weapon",
    "drug",
)

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b(?:\+?\d[\s-]?){7,15}\b"),
}

ALLOWED_ACTIONS = frozenset({"answer", "ask_clarifying_question", "praise", "recap"})


@dataclass
class FirewallResult:
    allowed: bool
    reason: str | None = None
    redacted_text: str = ""
    flags: list[str] = field(default_factory=list)


def redact_pii(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    redacted = text
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(redacted):
            flags.append(f"pii:{label}")
            redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted, flags


def check_content_policy(text: str) -> tuple[bool, str | None]:
    lowered = text.lower()
    for topic in BLOCKED_TOPICS:
        if topic in lowered:
            return False, f"blocked_topic:{topic}"
    return True, None


def check_action(action: str) -> tuple[bool, str | None]:
    if action not in ALLOWED_ACTIONS:
        return False, f"disallowed_action:{action}"
    return True, None


def run(child_input: str, requested_action: str = "answer") -> FirewallResult:
    """Single entrypoint the API layer calls before touching the model."""
    redacted_text, pii_flags = redact_pii(child_input)

    ok, reason = check_content_policy(redacted_text)
    if not ok:
        return FirewallResult(allowed=False, reason=reason, redacted_text=redacted_text, flags=pii_flags)

    ok, reason = check_action(requested_action)
    if not ok:
        return FirewallResult(allowed=False, reason=reason, redacted_text=redacted_text, flags=pii_flags)

    return FirewallResult(allowed=True, redacted_text=redacted_text, flags=pii_flags)
