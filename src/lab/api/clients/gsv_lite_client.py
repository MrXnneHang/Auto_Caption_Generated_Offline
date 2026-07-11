from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from loguru import logger

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest

if TYPE_CHECKING:
    from lab.api.types import GSVLiteResponse


DEFAULT_SAMPLE_RATE = 32000


class GSVLiteRequest(BaseRequest):
    text: str
    ref_audio_path: str | None = None
    ref_text: str | None = None
    speaker_audio_path: str | None = None
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    repetition_penalty: float = 1.35
    noise_scale: float = 0.5
    speed: float = 1.0


class GSVLiteClient(BaseClientInterface):
    def __init__(self) -> None:
        self.base_url = self.base_url + "/tts/gsv-lite/generate"
        self.last_error: str | None = None

    @staticmethod
    def _build_response(audio_bytes: bytes) -> GSVLiteResponse:
        return {
            "audio_type": "wav",
            "audio_rate": DEFAULT_SAMPLE_RATE,
            "audio_byte": audio_bytes,
        }

    def post(self, request: GSVLiteRequest) -> GSVLiteResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None
        if request.speaker_audio_path and not Path(request.speaker_audio_path).exists():
            self.last_error = f"Speaker audio file does not exist: {request.speaker_audio_path}"
            logger.error(self.last_error)
            return None

        self.last_error = None
        started = perf_counter()

        try:
            response = self.session.post(self.base_url, json=request.model_dump(exclude_none=True))
            response.raise_for_status()
            logger.info(
                "[GSVLiteClient] request succeeded in {:.2f}s text_len={}",
                perf_counter() - started,
                len(request.text),
            )
            return self._build_response(response.content)
        except Exception as exc:
            self.last_error = f"GSV-Lite request failed: {exc}"
            logger.error(self.last_error)
            return None

    async def asyncpost(self, request: GSVLiteRequest) -> GSVLiteResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None
        if request.speaker_audio_path and not Path(request.speaker_audio_path).exists():
            self.last_error = f"Speaker audio file does not exist: {request.speaker_audio_path}"
            logger.error(self.last_error)
            return None

        self.async_session = await self.get_async_session()
        self.last_error = None
        started = perf_counter()

        try:
            async with self.async_session.post(self.base_url, json=request.model_dump(exclude_none=True)) as response:
                if response.status != 200:
                    self.last_error = f"GSV-Lite HTTP {response.status}: {await response.text()}"
                    logger.error(self.last_error)
                    return None
                audio_bytes = await response.read()
                logger.info(
                    "[GSVLiteClient] request succeeded in {:.2f}s text_len={}",
                    perf_counter() - started,
                    len(request.text),
                )
                return self._build_response(audio_bytes)
        except Exception as exc:
            self.last_error = f"GSV-Lite request failed: {exc}"
            logger.error(self.last_error)
            return None
        finally:
            try:
                await self.async_session.close()
            finally:
                self.async_session = None
