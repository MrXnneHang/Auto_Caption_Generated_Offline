from __future__ import annotations

from loguru import logger
from pydantic import Field

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest, BaseResponse
from lab.api.types import LLMTranslateResponse


class LLMTranslateRequest(BaseRequest):
    text: str
    target_language: str = Field(default="ZH")


class LLMTranslateResponseModel(BaseResponse):
    source_text: str
    target_text: str

    def to_dict(self) -> LLMTranslateResponse:
        return LLMTranslateResponse(
            source_text=self.source_text,
            target_text=self.target_text,
        )


class LLMTranslateClient(BaseClientInterface):
    def __init__(self):
        self.base_url = self.base_url + "/translate/llm"

    def post(self, request: LLMTranslateRequest) -> LLMTranslateResponse | None:
        response = self.session.post(self.base_url, json=request.model_dump())
        response.raise_for_status()
        response_data = response.json()
        try:
            validated = LLMTranslateResponseModel.model_validate(response_data)
            return validated.to_dict()
        except Exception as exc:
            logger.error("Failed to parse LLM translate response: {}, {}", exc, response_data)
            return None

    async def asyncpost(self, request: LLMTranslateRequest) -> LLMTranslateResponse | None:
        self.async_session = await self.get_async_session()
        async with self.async_session.post(self.base_url, json=request.model_dump()) as response:
            if response.status != 200:
                logger.error("Failed to get a valid LLM translate response: {}", response.status)
                return None

            response_data = await response.json()
            try:
                validated = LLMTranslateResponseModel.model_validate(response_data)
                return validated.to_dict()
            except Exception as exc:
                logger.error("Failed to parse LLM translate response: {}, {}", exc, response_data)
                return None
            finally:
                await self.async_session.close()
