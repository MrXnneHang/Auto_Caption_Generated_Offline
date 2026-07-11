"""基于 AgentCore 的自主对话接口。"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from lab.agent.output_types import ToolCallEvent
from lab.history_storage.store import HistoryStorage

if TYPE_CHECKING:
    from lab.agent.core import AgentCore


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    model: str | None = None
    model_config = {"extra": "allow"}


class ChatResponse(BaseModel):
    session_id: str
    content: str
    model: str
    created: int


class ChatState:
    """在服务启动阶段填充的可变单例状态。"""

    chat_model: str = ""
    history_storage_dir: str = "conversations"
    workspace_root: str = ""
    agent_core: AgentCore | None = None

    @property
    def conversations_dir(self) -> str:
        """兼容旧命名，返回历史存储目录。"""
        return self.history_storage_dir

    @conversations_dir.setter
    def conversations_dir(self, value: str) -> None:
        """兼容旧命名，允许继续写入历史存储目录。"""
        self.history_storage_dir = value


chat_state = ChatState()
chat_router = APIRouter()


@chat_router.post("/chat", response_model=None)
async def chat_endpoint(request: ChatRequest, http_request: Request) -> JSONResponse:
    del http_request

    if chat_state.agent_core is None:
        raise HTTPException(status_code=503, detail="Chat endpoint not initialized: agent_core is None")

    log = logger.bind(group="chat")
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    log.info(f"Chat request: session={session_id}, message_len={len(request.message)}")

    from datetime import datetime, timezone

    date_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # noqa: UP017
    model = request.model or chat_state.chat_model
    assistant_content = ""

    try:
        async for token in chat_state.agent_core.run_turn(user_text=request.message):
            if isinstance(token, ToolCallEvent):
                continue
            assistant_content += token
    except Exception as exc:
        import traceback

        log.error(f"LLM error: {exc}")
        log.error(traceback.format_exc())
        raise HTTPException(
            status_code=502,
            detail=f"LLM error: {type(exc).__name__}: {exc}",
        ) from exc

    log.info(f"LLM response: {len(assistant_content)} chars")

    response = ChatResponse(
        session_id=session_id,
        content=assistant_content,
        model=model,
        created=int(time.time()),
    )
    log.info(f"Chat response sent (session={session_id}, date={date_id})")
    return JSONResponse(content=json.loads(response.model_dump_json()))


@chat_router.get("/sessions", response_model=None)
async def list_sessions() -> JSONResponse:
    history_store = HistoryStorage(base_dir=chat_state.history_storage_dir)
    dates = history_store.list_conversations()
    return JSONResponse(content={"sessions": dates, "count": len(dates)})


@chat_router.get("/chat/health", response_model=None)
async def chat_health() -> JSONResponse:
    core = chat_state.agent_core
    return JSONResponse(
        content={
            "status": "ok",
            "agent_core_ready": core is not None,
            "model": chat_state.chat_model,
            "conversations_dir": chat_state.history_storage_dir,
            "history_storage_dir": chat_state.history_storage_dir,
        }
    )
