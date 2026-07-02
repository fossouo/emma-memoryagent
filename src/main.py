"""Emma MemoryAgent — FastAPI entrypoint.

Request flow: child input -> Agent Firewall -> Memory Store -> Qwen Cloud -> response.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import agent_firewall, memory_store, qwen_client

app = FastAPI(title="Emma MemoryAgent", version="0.1.0")


class ChatRequest(BaseModel):
    child_id: str
    message: str
    action: str = "answer"
    topic: str | None = None


class ChatResponse(BaseModel):
    reply: str
    flags: list[str]
    already_covered: bool


SYSTEM_PROMPT_TEMPLATE = """You are Emma, a warm, patient learning companion for children.
Never repeat material the child has already covered unless they ask to review it.
Never praise the same specific achievement twice — vary encouragement or move forward.

Known covered topics for this child: {covered_topics}
Known preferences for this child: {preferences}
"""


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    firewall_result = agent_firewall.run(req.message, requested_action=req.action)
    if not firewall_result.allowed:
        raise HTTPException(status_code=403, detail=firewall_result.reason)

    memory = memory_store.load(req.child_id)
    already_covered = bool(req.topic and memory.has_covered(req.topic))

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        covered_topics=", ".join(memory.covered_topics) or "none yet",
        preferences=memory.preferences or "none recorded",
    )

    reply = qwen_client.chat(system_prompt, firewall_result.redacted_text)

    if req.topic:
        memory_store.record_topic_covered(req.child_id, req.topic)

    return ChatResponse(reply=reply, flags=firewall_result.flags, already_covered=already_covered)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
