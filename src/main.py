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


class ChatResponse(BaseModel):
    reply: str
    flags: list[str]
    already_covered: bool
    redacted_text: str
    retrieved_topic: str | None
    retrieved_status: str | None
    context_topics_sent: list[str]


class TopicRecord(BaseModel):
    status: str
    first_seen: float
    last_seen: float
    in_context_budget: bool


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

{retrieval_instruction}

Known preferences for this child: {preferences}
"""


def _format_context_lines(memory: memory_store.ChildMemory, context_topics: list[str]) -> str:
    if not context_topics:
        return "none yet"
    lines = []
    for t in context_topics:
        rec = memory.topics[t]
        lines.append(f"- {t}: status={rec['status']}")
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
    if not target_topic:
        recent = memory.most_recent_topic()
        if recent:
            target_topic = recent
            retrieved_topic = recent
            retrieved_status = memory.topics[recent]["status"]

    already_covered = bool(target_topic and memory.has_covered(target_topic))

    retrieval_instruction = ""
    if retrieved_topic:
        retrieval_instruction = (
            f"The child did not name a topic this turn. Their most recent topic was "
            f"'{retrieved_topic}' (status: {retrieved_status}). Continue with that topic and "
            f"adapt the difficulty to its status — e.g. a fresh follow-up exercise if "
            f"'practicing', a light recap if 'started'."
        )

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        context_lines=_format_context_lines(memory, context_topics),
        retrieval_instruction=retrieval_instruction,
        preferences=memory.preferences or "none recorded",
    )

    reply = qwen_client.chat(system_prompt, firewall_result.redacted_text)

    if target_topic:
        memory_store.record_topic_covered(req.child_id, target_topic)

    return ChatResponse(
        reply=reply,
        flags=firewall_result.flags,
        already_covered=already_covered,
        redacted_text=firewall_result.redacted_text,
        retrieved_topic=retrieved_topic,
        retrieved_status=retrieved_status,
        context_topics_sent=context_topics,
    )


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
