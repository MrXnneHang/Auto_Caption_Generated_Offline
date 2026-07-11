from __future__ import annotations

from typing import Literal

from loguru import logger

from lab.api.clients.base_client_interface import BaseClientInterface, BaseResponse


class ReloadClient(BaseClientInterface):
    def __init__(self, model_node: Literal["asr"]):
        self.base_url = self.base_url + f"/{model_node}/reload"

    def post(self) -> None:
        response = self.session.post(self.base_url)
        response.raise_for_status()
        try:
            response = BaseResponse.model_validate(response.json())  # 转换为 Pydantic 模型
        except Exception as e:
            logger.error(f"Failed to parse Reload response: {e}, {response}")
            return None

    async def asyncpost(self) -> None:
        """
        Asynchronous wrapper for the post method.
        """
        self.async_session = await self.get_async_session()
        async with self.async_session.post(self.base_url) as response:
            response.raise_for_status()
            try:
                response = BaseResponse.model_validate(response.json())  # 转换为 Pydantic 模型
            except Exception as e:
                logger.error(f"Failed to parse Reload response: {e}, {response}")
                return None


# vad_client = VADClient()
# result = vad_client.post(VADRequest(file_path=Path("voices/example1.wav")))
