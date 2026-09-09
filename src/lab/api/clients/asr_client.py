from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import aiohttp

from lab.api.clients.base_client_interface import BaseClientInterface, BaseRequest, BaseResponse
from lab.asr.converter import convert_asr_response_to_sentences
from lab.asr.types import ASRResponse, Sentence
from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.logger.logger_group import logger

if TYPE_CHECKING:
    from pathlib import Path

logger = cast("Any", logger)
_asr_logger: Any = logger.bind(group="asr")


class ASRRequest(BaseRequest):
    file_path: Path
    only_text: bool = False
    model_name: str | None = None


ASRRequest.model_rebuild(_types_namespace={"Path": __import__("pathlib").Path})


class ASRResponseModel(BaseResponse):
    key: str
    text: str
    timestamp: list[list[int]]

    def to_dict(self) -> ASRResponse:
        """将响应模型转换为标准 ASRResponse。

        Args:
            None.

        Returns:
            ASRResponse: 标准化后的 ASR 响应。

        Raises:
            None.
        """
        return ASRResponse(
            key=self.key,
            text=self.text,
            timestamp=self.timestamp,
        )


class ASRClient(BaseClientInterface):
    @staticmethod
    def _can_convert_to_sentences(asr_response: ASRResponse) -> bool:
        words = [word for word in asr_response["text"].split(" ") if word]
        return bool(words) and len(words) == len(asr_response["timestamp"])

    @staticmethod
    def _format_qwen_route_model(model_name: str) -> str:
        """将 Qwen 模型名格式化为路由要求的大小写。

        Args:
            model_name: 原始模型名。

        Returns:
            str: 路由使用的模型名。

        Raises:
            RuntimeError: 模型名不受支持时抛出。
        """
        normalized = model_name.strip().lower()
        alias_map = {
            "0.6b": "0.6B",
            "0.6": "0.6B",
            "qwen3-asr-0.6b": "0.6B",
            "1.7b": "1.7B",
            "1.7": "1.7B",
            "qwen3-asr-1.7b": "1.7B",
        }
        resolved = alias_map.get(normalized)
        if resolved is None:
            raise RuntimeError(f"Unsupported Qwen3-ASR model: {model_name}")
        return resolved

    def __init__(self, lab_setting: XnneHangLabSettings | None = None) -> None:
        """初始化 ASR HTTP 客户端。"""
        self.base_url = self.base_url
        self.last_error: str | None = None
        self._lab_setting = lab_setting

    def _resolve_effective_provider(self, settings: XnneHangLabSettings) -> str:
        """解析当前请求实际使用的 ASR provider。"""
        provider = settings.asr.asr_model_provider
        sherpa_ok = getattr(settings.package, "sherpa_asr", True)
        qwen_ok = getattr(settings.package, "qwen_asr", True)

        if provider == "sherpa" and sherpa_ok:
            return "sherpa"
        if provider == "qwen" and qwen_ok:
            return "qwen"
        # Fallback to any still-enabled provider
        if sherpa_ok:
            return "sherpa"
        if qwen_ok:
            return "qwen"
        raise RuntimeError(
            "ASR is disabled in lab.toml. Enable [package].sherpa_asr or [package].qwen_asr, or use text input."
        )

    def _resolve_qwen_route_model(self, request: ASRRequest) -> str:
        """解析 Qwen3-ASR 调用使用的端点模型名。

        Args:
            request: 当前请求对象。

        Returns:
            str: 路由使用的模型名。

        Raises:
            RuntimeError: Qwen3-ASR 服务未启用时抛出。
        """
        settings = self._lab_setting or load_settings_file("lab.toml", XnneHangLabSettings)
        if settings.asr.asr_model_provider != "qwen":
            raise RuntimeError("Qwen3-ASR is disabled in lab.toml")

        if request.model_name:
            return self._format_qwen_route_model(request.model_name)

        preload_models = settings.asr.qwen_asr.preload_models
        if preload_models:
            return self._format_qwen_route_model(preload_models[0])
        return "0.6B"

    def _resolve_base_url(self, request: ASRRequest) -> str:
        """根据当前配置解析 ASR 请求地址。

        Args:
            request: 当前请求对象。

        Returns:
            str: 目标接口地址。

        Raises:
            RuntimeError: 目标服务未启用时抛出。
        """
        settings = self._lab_setting or load_settings_file("lab.toml", XnneHangLabSettings)
        effective_provider = self._resolve_effective_provider(settings)
        if effective_provider == "qwen":
            model_name = self._resolve_qwen_route_model(request)
            return f"{self.base_url}/asr/qwen-asr/{model_name}/transcribe"

        return f"{self.base_url}/asr/sherpa/transcribe"

    def post(self, request: ASRRequest) -> list[Sentence] | None:
        """调用 ASR 接口并转换为句子列表。

        Args:
            request: 包含待识别音频路径的请求对象。

        Returns:
            list[Sentence] | None: 成功时返回句子列表，失败时返回 None。

        Raises:
            None.
        """
        if not request.file_path.exists():
            self.last_error = f"File not found: {request.file_path}"
            _asr_logger.error(self.last_error)
            return None

        self.last_error = None

        try:
            base_url = self._resolve_base_url(request)
            with request.file_path.open("rb") as file:
                response = self.session.post(base_url, files={"file": file})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self.last_error = f"ASR request failed: {exc}"
            _asr_logger.error(self.last_error)
            return None

        if payload.get("code") not in (None, 200, "200"):
            self.last_error = str(payload.get("message", "ASR request failed"))
            _asr_logger.error(f"ASR server returned error payload: {payload}")
            return None

        try:
            asr_response: ASRResponse = ASRResponseModel.model_validate(payload).to_dict()
            if not self._can_convert_to_sentences(asr_response):
                self.last_error = (
                    "ASR response does not contain sentence-convertible timestamps. "
                    "Qwen-ASR OpenVINO requires ForcedAligner to generate subtitles."
                )
                _asr_logger.error(f"{self.last_error}: {payload}")
                return None
            sentences = convert_asr_response_to_sentences(asr_response)
            if not sentences:
                self.last_error = "ASR returned no sentences."
                _asr_logger.error(f"ASR returned no sentences: {payload}")
                return None
            return sentences
        except Exception as exc:
            self.last_error = f"Failed to parse ASR response: {exc}"
            _asr_logger.error(f"Failed to parse ASR response: {exc}, {payload}")
            return None

    async def asyncpost(self, request: ASRRequest) -> ASRResponse | None:
        """异步调用 ASR 接口。

        Args:
            request: 包含待识别音频路径的请求对象。

        Returns:
            ASRResponse | None: 成功时返回标准 ASR 响应，失败时返回 None。

        Raises:
            None.
        """
        session = cast("Any", await self.get_async_session())
        self.async_session = session
        if not request.file_path.exists():
            self.last_error = f"File not found: {request.file_path}"
            _asr_logger.error(self.last_error)
            return None

        self.last_error = None

        try:
            base_url = self._resolve_base_url(request)
            with request.file_path.open("rb") as file:
                form = cast("Any", aiohttp.FormData())
                form.add_field("file", file, filename=request.file_path.name)
                async with session.post(base_url, data=form) as response:
                    if response.status != 200:
                        self.last_error = f"Failed to get a valid response: {response.status}"
                        _asr_logger.error(self.last_error)
                        return None

                    payload = await response.json()
        except Exception as exc:
            self.last_error = f"ASR request failed: {exc}"
            _asr_logger.error(self.last_error)
            return None
        finally:
            await session.close()

        try:
            return ASRResponseModel.model_validate(payload).to_dict()
        except Exception as exc:
            self.last_error = f"Failed to parse ASR response: {exc}"
            _asr_logger.error(f"Failed to parse ASR response: {exc}, {payload}")
            return None
