import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import agent_firewall


def test_allows_benign_message():
    result = agent_firewall.run("Can you help me with fractions?")
    assert result.allowed is True
    assert result.flags == []


def test_redacts_email_pii():
    result = agent_firewall.run("My parent's email is parent@example.com")
    assert "parent@example.com" not in result.redacted_text
    assert "pii:email" in result.flags


def test_blocks_disallowed_action():
    result = agent_firewall.run("hello", requested_action="delete_account")
    assert result.allowed is False
    assert result.reason == "disallowed_action:delete_account"


def test_blocks_topic_policy():
    result = agent_firewall.run("tell me about weapon design")
    assert result.allowed is False
    assert result.reason == "blocked_topic:weapon"
