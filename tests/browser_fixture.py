"""Run only for manual browser QA: python -m tests.browser_fixture.

Uses the synthetic fixture and scripted provider. No production fallback and no
external model calls. This server labels itself as a test fixture in the UI.
"""

from pathlib import Path

import uvicorn

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import SupportCheck
from kbfromyt.chat.history import History
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.models import VideoInput
from kbfromyt.store import Store
from kbfromyt.web.app import create_app
from tests.test_chat import ScriptedProvider


class BrowserProvider(ScriptedProvider):
    async def respond(self, items, instructions, schema, tools, choice):
        question = next((i["content"] for i in reversed(items) if i.get("role") == "user"), "")
        if schema is not SupportCheck:
            self.mode = (
                "empty"
                if "tiramis" in question.casefold()
                else "partial"
                if "weather" in question.casefold()
                else "error"
                if "API failure" in question
                else "grounded"
            )
        return await super().respond(items, instructions, schema, tools, choice)


class BrowserService(ChatService):
    def status(self):
        return {
            **super().status(),
            "message": (
                "BROWSER TEST FIXTURE · Synthetic source and scripted answers · No live model calls"
            ),
        }


if __name__ == "__main__":
    db = Path("data/live/browser-fixture.sqlite3")
    with Store(db) as store:
        store.import_video(VideoInput.model_validate_json(Path("examples/demo.json").read_text()))
    config = ChatConfig(db=db, semantic=False)
    uvicorn.run(
        create_app(
            config,
            BrowserService(
                config,
                BrowserProvider(),
                Corpus(config),
                history=History(Path("data/live/browser-fixture-state.sqlite3")),
            ),
        ),
        host="127.0.0.1",
        port=8001,
    )
