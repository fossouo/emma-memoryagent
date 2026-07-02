"""Emma MemoryAgent — FastAPI entrypoint.

Request flow: child input -> Agent Firewall -> Memory Store (retrieve +
bound context) -> Qwen Cloud -> Memory Store (update) -> response.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent_firewall, memory_store, qwen_client

app = FastAPI(title="Emma MemoryAgent", version="0.1.0")

WEB_DIR = Path(__file__).parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/demo", StaticFiles(directory=str(WEB_DIR), html=True), name="demo")

CONTEXT_BUDGET = 3  # max topics sent into the model's context per turn


class ChatRequest(BaseModel):
    child_id: str
    message: str
    action: str = "answer"
    topic: str | None = None
    skill: str | None = None
    homework_mode: bool = False


class PreferencesUpdate(BaseModel):
    """Seeds long-term preferences, as if learned in a prior session.

    Kept as a separate endpoint from /chat on purpose: in the demo this
    represents established memory from a previous day, not something the
    model just read out of the current message.
    """

    interests: list[str] = []
    struggles_with: list[str] = []


class PreferencesUsed(BaseModel):
    interests: list[str]
    struggles_with: list[str]


class ChatResponse(BaseModel):
    reply: str
    flags: list[str]
    already_covered: bool
    redacted_text: str
    retrieved_topic: str | None
    retrieved_status: str | None
    retrieved_skill: str | None
    retrieved_support_style: str | None
    context_topics_sent: list[str]
    preferences_used: PreferencesUsed
    support_style: str | None


class TopicRecord(BaseModel):
    status: str
    first_seen: float
    last_seen: float
    in_context_budget: bool
    skill: str | None = None
    support_style: str | None = None


class MemoryResponse(BaseModel):
    child_id: str
    topics: dict[str, TopicRecord]
    praise_log: list[str]
    preferences: dict


SYSTEM_PROMPT_TEMPLATE = """You are Emma, a warm, patient learning companion for children.
Never repeat material the child has already covered unless they ask to review it.
Never praise the same specific achievement twice — vary encouragement or move forward.

Recent learning context for this child (most relevant topics only — older
topics are stored but intentionally left out of this prompt to keep context
tight):
{context_lines}

{homework_instruction}

{retrieval_instruction}

{preferences_instruction}
"""

HOMEWORK_INSTRUCTION = (
    "This is homework help. Do NOT give the direct final answer. Guide the "
    "child with hints and reasoning questions instead — ask what they notice, "
    "what they'd try first, what a similar simpler case looks like. Only "
    "confirm correctness after the child attempts it themselves. This is a "
    "'hints, not answers' policy — it is a support_style stored in memory, "
    "not a one-off instruction, so keep using it on this topic going forward "
    "even if not repeated."
)


def _format_context_lines(memory: memory_store.ChildMemory, context_topics: list[str]) -> str:
    if not context_topics:
        return "none yet"
    lines = []
    for t in context_topics:
        rec = memory.topics[t]
        extra = []
        if rec.get("skill"):
            extra.append(f"skill={rec['skill']}")
        if rec.get("support_style"):
            extra.append(f"support_style={rec['support_style']}")
        extra_str = (", " + ", ".join(extra)) if extra else ""
        lines.append(f"- {t}: status={rec['status']}{extra_str}")
    return "\n".join(lines)


def _format_preferences_instruction(preferences: dict) -> str:
    interests = preferences.get("interests", [])
    struggles = preferences.get("struggles_with", [])
    if not interests and not struggles:
        return "No long-term preferences known yet for this child."

    lines = ["Long-term preferences known for this child (from prior sessions):"]
    if interests:
        lines.append(
            f"- Interests: {', '.join(interests)}. Weave these into examples "
            f"UNPROMPTED, even if the child's current message doesn't mention them."
        )
    if struggles:
        lines.append(
            f"- Known struggle areas: {', '.join(struggles)}. Adapt your teaching "
            f"approach away from that struggle (e.g. if the struggle is visual "
            f"fractions, prefer a verbal/step-by-step approach over diagrams)."
        )
    return "\n".join(lines)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    firewall_result = agent_firewall.run(req.message, requested_action=req.action)
    if not firewall_result.allowed:
        raise HTTPException(status_code=403, detail=firewall_result.reason)

    memory = memory_store.load(req.child_id)
    context_topics = memory.top_k_topics(CONTEXT_BUDGET)

    # Retrieval: if the child didn't name a topic, fall back to the most
    # recently touched one from memory — this is the "MemoryAgent" behavior,
    # not just persistence. already_covered / retrieved_* tell the caller
    # (and the UI) that this turn was shaped by prior memory, not a blank slate.
    target_topic = req.topic
    retrieved_topic = None
    retrieved_status = None
    retrieved_skill = None
    retrieved_support_style = None
    if not target_topic:
        recent = memory.most_recent_topic()
        if recent:
            target_topic = recent
            retrieved_topic = recent
            retrieved_status = memory.topics[recent]["status"]
            retrieved_skill = memory.topics[recent].get("skill")
            retrieved_support_style = memory.topics[recent].get("support_style")

    already_covered = bool(target_topic and memory.has_covered(target_topic))

    # support_style: explicit on this turn (homework_mode), or inherited from
    # what's already stored for the retrieved/named topic — a "hints, not
    # answers" policy set once keeps applying without needing to be repeated.
    existing_style = memory.topics.get((target_topic or "").lower(), {}).get("support_style")
    support_style = "hints_not_answers" if req.homework_mode else (retrieved_support_style or existing_style)

    retrieval_instruction = ""
    if retrieved_topic:
        retrieval_instruction = (
            f"The child did not name a topic this turn. Their most recent topic was "
            f"'{retrieved_topic}' (status: {retrieved_status}"
            + (f", skill: {retrieved_skill}" if retrieved_skill else "")
            + f"). Continue with that topic and adapt the difficulty to its status — "
            f"e.g. a fresh follow-up exercise if 'practicing', a light recap if 'started'. "
            f"Instead of starting from zero, continue from what the child already practiced."
        )

    homework_instruction = HOMEWORK_INSTRUCTION if support_style == "hints_not_answers" else ""

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        context_lines=_format_context_lines(memory, context_topics),
        homework_instruction=homework_instruction,
        retrieval_instruction=retrieval_instruction,
        preferences_instruction=_format_preferences_instruction(memory.preferences),
    )

    reply = qwen_client.chat(system_prompt, firewall_result.redacted_text)

    if target_topic:
        memory_store.record_topic_covered(
            req.child_id, target_topic, skill=req.skill, support_style=support_style
        )

    return ChatResponse(
        reply=reply,
        flags=firewall_result.flags,
        already_covered=already_covered,
        redacted_text=firewall_result.redacted_text,
        retrieved_topic=retrieved_topic,
        retrieved_status=retrieved_status,
        retrieved_skill=retrieved_skill,
        retrieved_support_style=retrieved_support_style,
        context_topics_sent=context_topics,
        preferences_used=PreferencesUsed(
            interests=memory.preferences.get("interests", []),
            struggles_with=memory.preferences.get("struggles_with", []),
        ),
        support_style=support_style,
    )


@app.put("/memory/{child_id}/preferences", response_model=MemoryResponse)
def set_preferences(child_id: str, prefs: PreferencesUpdate) -> MemoryResponse:
    memory = memory_store.load(child_id)
    interests = memory.preferences.setdefault("interests", [])
    for i in prefs.interests:
        if i not in interests:
            interests.append(i)
    struggles = memory.preferences.setdefault("struggles_with", [])
    for s in prefs.struggles_with:
        if s not in struggles:
            struggles.append(s)
    memory_store.save(memory)
    return get_memory(child_id)


@app.get("/memory/{child_id}", response_model=MemoryResponse)
def get_memory(child_id: str) -> MemoryResponse:
    memory = memory_store.load(child_id)
    context_topics = set(memory.top_k_topics(CONTEXT_BUDGET))
    topics = {
        t: TopicRecord(**rec, in_context_budget=(t in context_topics))
        for t, rec in memory.topics.items()
    }
    return MemoryResponse(
        child_id=memory.child_id,
        topics=topics,
        praise_log=memory.praise_log,
        preferences=memory.preferences,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
