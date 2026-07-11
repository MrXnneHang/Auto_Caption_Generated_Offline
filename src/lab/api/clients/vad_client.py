from __future__ import annotations

# ASRRequest` is not fully defined; you should define `Path`, then call `ASRRequest.model_rebuild()`.
from pathlib import Path  # noqa: TC003

from loguru import logger

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest, BaseResponse
from lab.asr.types import VadResponse


class VADRequest(BaseRequest):
    file_path: Path


class VADResponseModel(BaseResponse):
    key: str
    timestamp: list[list[int]]
    audio_length: int

    def to_dict(self) -> VadResponse:
        return VadResponse(
            key=self.key,
            timestamp=self.timestamp,
            audio_length=self.audio_length,
        )


class VADClient(BaseClientInterface):
    def __init__(self):
        self.base_url = self.base_url + "/audio/vad"

    def post(self, request: VADRequest) -> VadResponse | None:
        """封装语音活动检测接口"""
        if not request.file_path.exists():
            logger.error(f"File not found: {request.file_path}")
            return None
        with request.file_path.open("rb") as f:
            response = self.session.post(self.base_url, files={"file": f})
            response.raise_for_status()
            try:
                return VADResponseModel.model_validate(response.json()).to_dict()  # 转换为 Pydantic 模型
            except Exception as e:
                logger.error(f"Failed to parse VAD response: {e}, {response}")
                return None

    async def asyncpost(self, request: VADRequest) -> VadResponse | None:
        """封装语音活动检测接口的异步版本"""
        self.async_session = await self.get_async_session()
        if not request.file_path.exists():
            logger.error(f"File not found: {request.file_path}")
            return None
        with request.file_path.open("rb") as f:
            async with self.async_session.post(self.base_url, data={"file": f}) as response:
                response_data = await response.json()
                try:
                    return VADResponseModel.model_validate(response_data).to_dict()  # 转换为 Pydantic 模型
                except Exception as e:
                    logger.error(f"Failed to parse VAD response: {e}, {response_data}")
                    return None
                finally:
                    await self.async_session.close()


# vad_client = VADClient()
# result = vad_client.post(VADRequest(file_path=Path("voices/example1.wav")))
