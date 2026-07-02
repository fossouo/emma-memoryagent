import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import memory_store


def setup_function(_):
    tmp_dir = tempfile.mkdtemp()
    memory_store.DB_PATH = Path(tmp_dir) / "memory.sqlite3"


def test_new_child_has_empty_memory():
    memory = memory_store.load("child-1")
    assert memory.topics == {}
    assert memory.has_covered("fractions") is False
    assert memory.most_recent_topic() is None


def test_record_topic_covered_persists_with_started_status():
    memory_store.record_topic_covered("child-2", "fractions")
    memory = memory_store.load("child-2")
    assert memory.has_covered("fractions") is True
    assert memory.topics["fractions"]["status"] == "started"


def test_record_topic_covered_progresses_status_on_repeat():
    memory_store.record_topic_covered("child-3", "fractions")
    memory_store.record_topic_covered("child-3", "fractions")
    memory = memory_store.load("child-3")
    assert memory.topics["fractions"]["status"] == "practicing"


def test_most_recent_topic_tracks_last_touched():
    memory_store.record_topic_covered("child-4", "fractions")
    memory_store.record_topic_covered("child-4", "decimals")
    memory = memory_store.load("child-4")
    assert memory.most_recent_topic() == "decimals"


def test_top_k_topics_bounds_context():
    for topic in ["fractions", "decimals", "geometry", "multiplication"]:
        memory_store.record_topic_covered("child-5", topic)
    memory = memory_store.load("child-5")
    top2 = memory.top_k_topics(2)
    assert len(top2) == 2
    assert top2[0] == "multiplication"  # most recently touched first


def test_record_praise_is_idempotent():
    memory_store.record_praise("child-6", "finished the quiz")
    memory_store.record_praise("child-6", "finished the quiz")
    memory = memory_store.load("child-6")
    assert memory.praise_log.count("finished the quiz") == 1


def test_skill_and_support_style_persist():
    memory_store.record_topic_covered(
        "child-7", "fractions", skill="adding same-denominator fractions", support_style="hints_not_answers"
    )
    memory = memory_store.load("child-7")
    assert memory.topics["fractions"]["skill"] == "adding same-denominator fractions"
    assert memory.topics["fractions"]["support_style"] == "hints_not_answers"


def test_skill_and_support_style_carry_forward_when_not_repeated():
    memory_store.record_topic_covered(
        "child-8", "fractions", skill="adding same-denominator fractions", support_style="hints_not_answers"
    )
    memory_store.record_topic_covered("child-8", "fractions")
    memory = memory_store.load("child-8")
    assert memory.topics["fractions"]["skill"] == "adding same-denominator fractions"
    assert memory.topics["fractions"]["support_style"] == "hints_not_answers"
    assert memory.topics["fractions"]["status"] == "practicing"
