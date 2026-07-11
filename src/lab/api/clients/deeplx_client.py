from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import Field, field_validator

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest, BaseResponse
from lab.api.types import DeepLXResponse


class DeepLXRequest(BaseRequest):
    text: str  # 必须传入
    source_language: Literal["auto", "EN", "ZH", "JA"] = Field(default="auto")  # 默认自动检测
    target_language: Literal["EN", "ZH", "JA"] = Field(default="ZH")  # 默认中文

    @field_validator("source_language", mode="before")
    @classmethod
    def normalize_source_language(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.lower() == "auto":
            return "auto"
        return normalized.upper()

    @field_validator("target_language", mode="before")
    @classmethod
    def normalize_target_language(cls, value: str) -> str:
        return value.strip().upper()


class DeepLXResponseModel(BaseResponse):
    source_text: str
    target_text: str

    def to_dict(self) -> DeepLXResponse:
        return DeepLXResponse(
            source_text=self.source_text,
            target_text=self.target_text,
        )


class DeepLXClient(BaseClientInterface):
    def __init__(self):
        self.base_url = self.base_url + "/translate/deeplx"

    def post(self, request: DeepLXRequest) -> DeepLXResponse | None:
        response = self.session.post(self.base_url, json=request.model_dump())
        response.raise_for_status()
        response = response.json()
        try:
            response = DeepLXResponseModel.model_validate(response)  # 转换为 Pydantic 模型
            return response.to_dict()
        except Exception as e:
            logger.error(f"Failed to parse DeepLX response: {e}, {response}")
            return None

    async def asyncpost(self, request: DeepLXRequest) -> DeepLXResponse | None:
        """
        Asynchronous wrapper for the post method.
        """
        # bert-vits 的请求通常很久。所以生产环境应该异步。
        self.async_session = await self.get_async_session()
        async with self.async_session.post(self.base_url, json=request.model_dump()) as response:
            if response.status != 200:
                logger.error(f"Failed to get a valid response: {response.status}")
                return None
            response_data = await response.json()
            try:
                response = DeepLXResponseModel.model_validate(response_data)  # 转换为 Pydantic 模型
                return response.to_dict()
            except Exception as e:
                logger.error(f"Failed to parse DeepLX response: {e}, {response}")
                return None
            finally:
                await self.async_session.close()
