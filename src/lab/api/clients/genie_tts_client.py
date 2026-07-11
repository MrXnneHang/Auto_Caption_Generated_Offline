from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from loguru import logger

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest

if TYPE_CHECKING:
    from lab.api.types import GenieTTSResponse


DEFAULT_SAMPLE_RATE = 32000


class GenieTTSRequest(BaseRequest):
    text: str
    ref_audio_path: str | None = None
    ref_text: str | None = None


class GenieTTSClient(BaseClientInterface):
    def __init__(self) -> None:
        self.base_url = self.base_url + "/tts/genie-tts/generate"
        self.last_error: str | None = None

    @staticmethod
    def _build_response(audio_bytes: bytes) -> GenieTTSResponse:
        return {
            "audio_type": "wav",
            "audio_rate": DEFAULT_SAMPLE_RATE,
            "audio_byte": audio_bytes,
        }

    def post(self, request: GenieTTSRequest) -> GenieTTSResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None

        self.last_error = None
        started = perf_counter()

        try:
            response = self.session.post(self.base_url, json=request.model_dump(exclude_none=True))
            response.raise_for_status()
            logger.info(
                "[GenieTTSClient] request succeeded in {:.2f}s text_len={}",
                perf_counter() - started,
                len(request.text),
            )
            return self._build_response(response.content)
        except Exception as exc:
            self.last_error = f"Genie-TTS request failed: {exc}"
            logger.error(self.last_error)
            return None

    async def asyncpost(self, request: GenieTTSRequest) -> GenieTTSResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None

        self.async_session = await self.get_async_session()
        self.last_error = None
        started = perf_counter()

        try:
            async with self.async_session.post(self.base_url, json=request.model_dump(exclude_none=True)) as response:
                if response.status != 200:
                    self.last_error = f"Genie-TTS HTTP {response.status}: {await response.text()}"
                    logger.error(self.last_error)
                    return None
                audio_bytes = await response.read()
                logger.info(
                    "[GenieTTSClient] request succeeded in {:.2f}s text_len={}",
                    perf_counter() - started,
                    len(request.text),
                )
                return self._build_response(audio_bytes)
        except Exception as exc:
            self.last_error = f"Genie-TTS request failed: {exc}"
            logger.error(self.last_error)
            return None
        finally:
            try:
                await self.async_session.close()
            finally:
                self.async_session = None
