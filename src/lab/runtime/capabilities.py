from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from lab.config_manager import XnneHangLabSettings


class VoiceCapability(BaseModel):
    enabled: bool
    provider: str | None
    state: Literal["disabled", "available", "unavailable"]
    reason: str | None
    endpoints: list[str]


class RuntimeCapabilities(BaseModel):
    schema_version: Literal[1] = 1
    voice: dict[Literal["asr", "tts"], VoiceCapability]


def build_runtime_capabilities(settings: XnneHangLabSettings) -> RuntimeCapabilities:
    asr_provider = settings.asr.asr_model_provider
    tts_provider = settings.agent.tts.provider

    asr_package_enabled = {
        "sherpa": settings.package.sherpa_asr,
        "qwen": settings.package.qwen_asr,
    }.get(asr_provider, False)
    tts_package_enabled = {
        "gsv_lite": settings.package.gsv_lite,
        "genie_tts": settings.package.genie_tts,
        "qwen_tts": settings.package.qwen_tts,
    }.get(tts_provider, False)
    asr_enabled = asr_provider != "none" and asr_package_enabled
    tts_enabled = tts_provider != "none" and tts_package_enabled

    asr_endpoints: list[str] = []
    if asr_provider == "sherpa":
        asr_endpoints = ["/asr/reload", "/asr/sherpa/transcribe", "/asr/sherpa/vad"]
    elif asr_provider == "qwen":
        asr_endpoints = ["/asr/reload", "/asr/qwen-asr/{model}/transcribe"]

    tts_endpoints = {
        "gsv_lite": ["/tts/gsv-lite/health", "/tts/gsv-lite/generate"],
        "genie_tts": ["/tts/genie-tts/health", "/tts/genie-tts/generate"],
        "qwen_tts": ["/tts/qwen-tts/health", "/tts/qwen-tts/generate"],
    }.get(tts_provider, [])

    return RuntimeCapabilities(
        voice={
            "asr": VoiceCapability(
                enabled=asr_enabled,
                provider=asr_provider if asr_provider != "none" else None,
                state="available" if asr_enabled else "disabled" if asr_provider == "none" else "unavailable",
                reason=None if asr_enabled else "disabled_by_config" if asr_provider == "none" else "package_disabled",
                endpoints=asr_endpoints if asr_enabled else [],
            ),
            "tts": VoiceCapability(
                enabled=tts_enabled,
                provider=tts_provider if tts_provider != "none" else None,
                state="available" if tts_enabled else "disabled" if tts_provider == "none" else "unavailable",
                reason=None if tts_enabled else "disabled_by_config" if tts_provider == "none" else "package_disabled",
                endpoints=tts_endpoints if tts_enabled else [],
            ),
        }
    )
