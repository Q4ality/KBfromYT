from __future__ import annotations

import asyncio
import re
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import ChatRequest
from kbfromyt.chat.history import History
from kbfromyt.chat.memory import configure_tokenizer
from kbfromyt.chat.providers.openai import OpenAIProvider
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.store import Store
from kbfromyt.web.library import Library, PlaylistRequest

STATIC = Path(__file__).parent / "static"


def create_app(config: ChatConfig | None = None, service: ChatService | None = None) -> FastAPI:
    config = config or ChatConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service:
            app.state.chat = service
        else:
            corpus, problem = None, None
            try:
                await asyncio.to_thread(configure_tokenizer, config.model)
                corpus = await asyncio.to_thread(Corpus, config)
            except Exception:
                problem = (
                    "The tokenizer, source corpus or semantic index could not be opened. "
                    "Stop chat, check the paths and network access, and restart."
                )
            provider = OpenAIProvider(config) if config.has_key else None
            app.state.chat = ChatService(
                config, provider, corpus, problem, History(config.state_db)
            )
        app.state.library = (
            Library(app.state.chat, app.state.chat.history) if app.state.chat.history else None
        )
        if not service and app.state.library and config.db.is_file():
            with Store(config.db) as store:
                needs_cleanup = store.needs_reprocessing()
            if needs_cleanup:
                app.state.library.start()
        try:
            yield
        finally:
            if app.state.library:
                await app.state.library.close()
            await app.state.chat.close()

    app = FastAPI(
        title="KBfromYT", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        host = urlparse("http://" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Use the local application address."}, status_code=403)
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed."}, status_code=403
            )
        if request.method == "POST" and request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid content length."}, status_code=400)
        if size > 40000:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    async def status(request: Request):
        return request.app.state.chat.status()

    def owner(request: Request) -> str:
        token = request.cookies.get("kb_owner", "")
        return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else secrets.token_urlsafe(32)

    def owner_cookie(response: JSONResponse, token: str) -> JSONResponse:
        response.set_cookie("kb_owner", token, httponly=True, samesite="strict", max_age=31536000)
        return response

    @app.get("/api/conversations")
    async def conversations(request: Request, offset: int = 0):
        token = owner(request)
        history = request.app.state.chat.history
        rows = history.list(token, offset) if history else []
        return owner_cookie(
            JSONResponse({"conversations": rows[:100], "has_more": len(rows) > 100}), token
        )

    @app.get("/api/conversations/{key}")
    async def conversation(key: str, request: Request, before: int | None = None):
        history = request.app.state.chat.history
        if not history:
            raise HTTPException(404, "Saved conversations are unavailable.")
        try:
            return history.page(owner(request), key, before)
        except KeyError as exc:
            raise HTTPException(
                404, "Conversation not found in this browser's saved chats."
            ) from exc

    @app.get("/api/library")
    async def library_status(request: Request):
        library = request.app.state.library
        if not library:
            return {"videos": [], "playlists": [], "jobs": [], "active_job": None}
        return await asyncio.to_thread(library.status)

    @app.post("/api/library/import", status_code=202)
    async def import_playlist(body: PlaylistRequest, request: Request):
        return start_library(request, body)

    @app.post("/api/library/rebuild", status_code=202)
    async def rebuild_library(request: Request):
        return start_library(request)

    def start_library(request: Request, body: PlaylistRequest | None = None) -> dict:
        library = request.app.state.library
        if not library:
            raise HTTPException(503, "Library management is unavailable.")
        try:
            return library.start(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        token = owner(request)
        task = asyncio.create_task(
            request.app.state.chat.chat(request.cookies.get("kb_session"), body, token)
        )
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.2)
                if await request.is_disconnected():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise HTTPException(499, "Request cancelled.")
            key, reply = await task
        except ValueError as exc:
            raise HTTPException(503, "Chat session capacity reached. Try again later.") from exc
        except KeyError as exc:
            raise HTTPException(
                404, "Conversation not found in this browser's saved chats."
            ) from exc
        finally:
            if not task.done():
                task.cancel()
        response = JSONResponse(reply.model_dump(mode="json"))
        response.set_cookie("kb_session", key, httponly=True, samesite="strict")
        return owner_cookie(response, token)

    @app.post("/api/chat/reset")
    async def reset(request: Request):
        await request.app.state.chat.sessions.reset(request.cookies.get("kb_session"))
        response = JSONResponse({"reset": True})
        response.delete_cookie("kb_session")
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
