from pathlib import Path

import pytest

from kbfromyt.models import VideoInput
from kbfromyt.store import Store


@pytest.fixture
def video():
    return VideoInput.model_validate_json(
        (Path(__file__).parents[1] / "examples/demo.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "kb.sqlite3") as value:
        yield value
