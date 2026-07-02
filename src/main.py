"""Emma MemoryAgent — FastAPI entrypoint.

Request flow: child input -> Agent Firewall -> Memory Store -> Qwen Cloud -> response.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent_firewall, memory_store, qwen_client

app = FastAPI(title="Emma MemoryAgent", version="0.1.0")

WEB_DIR = Path(__file__).parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/demo", StaticFiles(directory=str(WEB_DIR), html=True), name="demo")


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


class MemoryResponse(BaseModel):
    child_id: str
    covered_topics: list[str]
    praise_log: list[str]
    preferences: dict


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

    return ChatResponse(
        reply=reply,
        flags=firewall_result.flags,
        already_covered=already_covered,
        redacted_text=firewall_result.redacted_text,
    )


@app.get("/memory/{child_id}", response_model=MemoryResponse)
def get_memory(child_id: str) -> MemoryResponse:
    memory = memory_store.load(child_id)
    return MemoryResponse(
        child_id=memory.child_id,
        covered_topics=memory.covered_topics,
        praise_log=memory.praise_log,
        preferences=memory.preferences,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
