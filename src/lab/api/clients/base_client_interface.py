from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import aiohttp
import requests
from loguru import logger
from pydantic import BaseModel, Field


class BaseRequest(BaseModel):
    datetime: str = Field(default=str(datetime.now()))  # 请求时间, default, 显式无需手动填写

    class Config:
        extra = "ignore"  # 兼容额外字段


class BaseResponse(BaseModel):
    datetime: str = Field(default=str(datetime.now()))  # 响应时间，default, 显式无需手动填写
    code: int = Field(default=200, description="响应状态码")
    message: str = Field(default="OK", description="响应消息")

    class Config:
        extra = "ignore"  # 兼容额外字段


class BaseClientInterface(ABC):
    """Base interface for all agent implementations"""

    base_url = "http://localhost:12393"
    session = requests.Session()
    async_session: aiohttp.ClientSession | None = None

    session.headers.update({"Accept": "application/json"})

    @abstractmethod
    def post(self, *args: Any, **kwargs: Any) -> Any:
        """
        Send a synchronous request to the server.

        Each client defines its own request/response shape, so the interface
        only fixes the method name (gradual signature keeps overrides valid).
        """
        logger.critical("BaseClient: No chat function set.")
        raise ValueError("BaseClient: No chat function set.")

    @classmethod
    async def get_async_session(cls) -> aiohttp.ClientSession:
        if cls.async_session is None or cls.async_session.closed:
            cls._async_session = aiohttp.ClientSession(headers={"Accept": "application/json"})
        return cls._async_session

    @abstractmethod
    async def asyncpost(self, *args: Any, **kwargs: Any) -> Any:
        """
        Asynchronous wrapper for the post method.
        """
        logger.warning("BaseClient: asyncpost is not implemented, using post instead.")
        return self.post(*args, **kwargs)
