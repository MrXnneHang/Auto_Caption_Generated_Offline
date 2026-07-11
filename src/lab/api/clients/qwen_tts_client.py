from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

import aiohttp
from loguru import logger

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest

if TYPE_CHECKING:
    from lab.api.types import QwenTTSResponse


class QwenTTSRequest(BaseRequest):
    text: str
    ref_audio_path: str | None = None
    ref_text: str | None = None


class QwenTTSClient(BaseClientInterface):
    def __init__(self) -> None:
        self.base_url = self.base_url + "/tts/qwen-tts/generate"
        self.last_error: str | None = None

    @staticmethod
    def _build_response(audio_bytes: bytes) -> QwenTTSResponse:
        return {
            "audio_type": "wav",
            "audio_rate": 24000,
            "audio_byte": audio_bytes,
        }

    def post(self, request: QwenTTSRequest) -> QwenTTSResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None

        self.last_error = None
        started = perf_counter()

        try:
            data = {
                "text": request.text,
                "ref_text": request.ref_text or "",
            }
            if request.ref_audio_path:
                with Path(request.ref_audio_path).open("rb") as ref_audio:
                    response = self.session.post(self.base_url, data=data, files={"ref_audio": ref_audio})
            else:
                data = {
                    "text": request.text,
                    "ref_text": request.ref_text or "",
                }
                response = self.session.post(self.base_url, data=data)
            response.raise_for_status()
            logger.info(
                "[QwenTTSClient] request succeeded in {:.2f}s text_len={}", perf_counter() - started, len(request.text)
            )
            return self._build_response(response.content)
        except Exception as exc:
            self.last_error = f"Qwen-TTS request failed: {exc}"
            logger.error(self.last_error)
            return None

    async def asyncpost(self, request: QwenTTSRequest) -> QwenTTSResponse | None:
        if request.ref_audio_path and not Path(request.ref_audio_path).exists():
            self.last_error = f"Reference audio file does not exist: {request.ref_audio_path}"
            logger.error(self.last_error)
            return None

        self.async_session = await self.get_async_session()
        self.last_error = None
        started = perf_counter()

        try:
            form = aiohttp.FormData()
            form.add_field("text", request.text)
            form.add_field("ref_text", request.ref_text or "")
            if request.ref_audio_path:
                ref_path = Path(request.ref_audio_path)
                with ref_path.open("rb") as ref_audio:
                    form.add_field("ref_audio", ref_audio, filename=ref_path.name, content_type="audio/wav")
                    async with self.async_session.post(self.base_url, data=form) as response:
                        if response.status != 200:
                            self.last_error = f"Qwen-TTS HTTP {response.status}: {await response.text()}"
                            logger.error(self.last_error)
                            return None
                        audio_bytes = await response.read()
                        logger.info(
                            "[QwenTTSClient] request succeeded in {:.2f}s text_len={}",
                            perf_counter() - started,
                            len(request.text),
                        )
                        return self._build_response(audio_bytes)

            async with self.async_session.post(self.base_url, data=form) as response:
                if response.status != 200:
                    self.last_error = f"Qwen-TTS HTTP {response.status}: {await response.text()}"
                    logger.error(self.last_error)
                    return None
                audio_bytes = await response.read()
                logger.info(
                    "[QwenTTSClient] request succeeded in {:.2f}s text_len={}",
                    perf_counter() - started,
                    len(request.text),
                )
                return self._build_response(audio_bytes)
        except Exception as exc:
            self.last_error = f"Qwen-TTS request failed: {exc}"
            logger.error(self.last_error)
            return None
        finally:
            try:
                await self.async_session.close()
            finally:
                self.async_session = None
