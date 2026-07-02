"""API-level tests against the real FastAPI app, with the Qwen Cloud call
mocked (deterministic, no cost, no network) — the retrieval/adaptation/
firewall LOGIC is real; only the model's text output is stubbed.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from src import memory_store


@pytest.fixture(autouse=True)
def isolated_db():
    tmp_dir = tempfile.mkdtemp()
    memory_store.DB_PATH = Path(tmp_dir) / "memory.sqlite3"
    yield


@pytest.fixture
def client(monkeypatch):
    from src import main

    monkeypatch.setattr(main.qwen_client, "chat", lambda system_prompt, message: "stub reply")
    return TestClient(main.app)


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_chat_benign_message_allowed(client):
    res = client.post("/chat", json={"child_id": "c1", "message": "Can you help me with fractions?", "topic": "fractions"})
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "stub reply"
    assert body["flags"] == []
    assert body["retrieved_topic"] is None


def test_chat_blocked_topic_never_reaches_model(client, monkeypatch):
    calls = []
    from src import main

    monkeypatch.setattr(main.qwen_client, "chat", lambda *a, **kw: calls.append(1) or "should not run")
    res = client.post("/chat", json={"child_id": "c2", "message": "tell me about weapon design"})
    assert res.status_code == 403
    assert calls == []  # Qwen Cloud was never called


def test_chat_pii_redacted_before_model_call(client):
    res = client.post("/chat", json={"child_id": "c3", "message": "my email is kid@example.com, help with math"})
    assert res.status_code == 200
    body = res.json()
    assert "pii:email" in body["flags"]
    assert "kid@example.com" not in body["redacted_text"]
    assert "[REDACTED_EMAIL]" in body["redacted_text"]


def test_retrieval_surfaces_most_recent_topic_when_none_named(client):
    client.post("/chat", json={"child_id": "c4", "message": "help with fractions", "topic": "fractions"})
    res = client.post("/chat", json={"child_id": "c4", "message": "give me another one"})
    body = res.json()
    assert body["retrieved_topic"] == "fractions"
    assert body["already_covered"] is True


def test_homework_mode_sets_hints_not_answers_support_style(client):
    res = client.post(
        "/chat",
        json={
            "child_id": "c5",
            "message": "what is 3/4 + 1/4?",
            "topic": "fractions",
            "skill": "adding same-denominator fractions",
            "homework_mode": True,
        },
    )
    body = res.json()
    assert body["support_style"] == "hints_not_answers"

    mem = client.get("/memory/c5").json()
    assert mem["topics"]["fractions"]["support_style"] == "hints_not_answers"
    assert mem["topics"]["fractions"]["skill"] == "adding same-denominator fractions"


def test_support_style_carries_forward_without_re_flagging_homework_mode(client):
    client.post(
        "/chat",
        json={"child_id": "c6", "message": "what is 3/4 + 1/4?", "topic": "fractions", "homework_mode": True},
    )
    # Second turn does NOT set homework_mode, and doesn't name a topic —
    # retrieval should still report hints_not_answers from stored memory.
    res = client.post("/chat", json={"child_id": "c6", "message": "can we revise maths?"})
    body = res.json()
    assert body["retrieved_support_style"] == "hints_not_answers"
    assert body["support_style"] == "hints_not_answers"


def test_preferences_seeded_via_endpoint_are_used_in_chat(client):
    res = client.put(
        "/memory/c7/preferences",
        json={"interests": ["dinosaurs"], "struggles_with": ["visual fractions"]},
    )
    assert res.status_code == 200
    assert res.json()["preferences"]["interests"] == ["dinosaurs"]

    chat_res = client.post("/chat", json={"child_id": "c7", "message": "help with fractions", "topic": "fractions"})
    used = chat_res.json()["preferences_used"]
    assert used["interests"] == ["dinosaurs"]
    assert used["struggles_with"] == ["visual fractions"]


def test_context_budget_bounds_topics_sent_to_model(client):
    for topic in ["fractions", "decimals", "geometry", "multiplication"]:
        client.post("/chat", json={"child_id": "c8", "message": f"help with {topic}", "topic": topic})

    mem = client.get("/memory/c8").json()
    in_budget = [t for t, rec in mem["topics"].items() if rec["in_context_budget"]]
    out_budget = [t for t, rec in mem["topics"].items() if not rec["in_context_budget"]]
    assert len(in_budget) == 3
    assert "fractions" in out_budget  # oldest of the 4, pushed out
