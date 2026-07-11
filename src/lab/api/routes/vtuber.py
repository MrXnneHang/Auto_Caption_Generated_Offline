from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, File, Response, WebSocket
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from lab.websocket_handler import WebSocketHandler

if TYPE_CHECKING:
    from lab.service_context import ServiceContext


class ClientWebSocketRouter(APIRouter):
    ws_handler: WebSocketHandler


def init_client_ws_route(default_context_cache: ServiceContext) -> ClientWebSocketRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = ClientWebSocketRouter()
    ws_handler = WebSocketHandler(default_context_cache)
    router.ws_handler = ws_handler

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        await websocket.accept()
        client_uid = str(uuid4())

        try:
            await ws_handler.handle_new_connection(websocket, client_uid)
            await ws_handler.handle_websocket_communication(websocket, client_uid)
        except WebSocketDisconnect:
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            await ws_handler.handle_disconnect(client_uid)
            raise

    return router


router = APIRouter()
file_default = File(...)


@router.get("/web-tool")
async def web_tool_redirect():
    """Redirect /web-tool to /web_tool/index.html"""
    return Response(status_code=302, headers={"Location": "/web-tool/index.html"})


@router.get("/web_tool")
async def web_tool_redirect_alt():
    """Redirect /web_tool to /web_tool/index.html"""
    return Response(status_code=302, headers={"Location": "/web-tool/index.html"})
