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
    assert memory.covered_topics == []
    assert memory.has_covered("fractions") is False


def test_record_topic_covered_persists():
    memory_store.record_topic_covered("child-2", "fractions")
    memory = memory_store.load("child-2")
    assert memory.has_covered("fractions") is True


def test_record_praise_is_idempotent():
    memory_store.record_praise("child-3", "finished the quiz")
    memory_store.record_praise("child-3", "finished the quiz")
    memory = memory_store.load("child-3")
    assert memory.praise_log.count("finished the quiz") == 1
