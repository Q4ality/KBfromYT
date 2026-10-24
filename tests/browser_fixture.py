"""Run only for manual browser QA: python -m tests.browser_fixture.

Uses the synthetic fixture and scripted provider. No production fallback and no
external model calls. This server labels itself as a test fixture in the UI.
"""

import asyncio
from pathlib import Path

import uvicorn
from fastapi.responses import JSONResponse

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
        if "QA interrupted request" in question and isinstance(choice, dict):
            await asyncio.sleep(3)
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
        source = VideoInput.model_validate_json(Path("examples/demo.json").read_text())
        store.import_video(source)
        second = source.model_copy(deep=True)
        second.video_id = "FIXTURE0002"
        second.title = "Second fixture: trajectory comparisons"
        store.import_video(second)
    config = ChatConfig(db=db, semantic=False)
    history = History(Path("data/live/browser-fixture-state.sqlite3"))
    history.save_playlist(
        {
            "id": "FIXTUREPLAY1",
            "url": "https://www.youtube.com/playlist?list=FIXTUREPLAY1",
            "video_ids": [source.video_id],
        }
    )
    history.save_playlist(
        {
            "id": "FIXTUREPLAY2",
            "url": "https://www.youtube.com/playlist?list=FIXTUREPLAY2",
            "video_ids": [second.video_id],
        }
    )
    app = create_app(
        config,
        BrowserService(
            config,
            BrowserProvider(),
            Corpus(config),
            history=history,
        ),
    )
    lost = set()

    @app.middleware("http")
    async def simulated_response_loss(request, call_next):
        body = await request.json() if request.url.path == "/api/chat" else {}
        response = await call_next(request)
        key = body.get("request_id")
        if body.get("message") == "QA lost response" and key not in lost:
            lost.add(key)
            print("BROWSER TEST FIXTURE: discarded completed response once", flush=True)
            return JSONResponse(
                {"detail": "TEST FIXTURE: simulated response loss"}, status_code=503
            )
        return response

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
    )
