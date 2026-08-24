from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, TypeGuard, cast

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, ValidationError

from lab.config_manager import TranslateProvider, XnneHangLabSettings, load_settings_file, write_settings_file
from lab.config_manager.agent import LLMProviderSetting, ThinkingMode, TTSProvider

ApiFormat = Literal["chat_completion"]
EmbeddingPoolingType = Literal["mean", "cls", "last"]
ALLOWED_API_FORMATS: tuple[ApiFormat, ...] = ("chat_completion",)
ALLOWED_EMBEDDING_POOLING_TYPES: tuple[EmbeddingPoolingType, ...] = ("mean", "cls", "last")
ALLOWED_THINKING_MODES: tuple[ThinkingMode, ...] = ("default", "enabled", "disabled")
ALLOWED_TTS_PROVIDERS: tuple[TTSProvider, ...] = ("none", "gsv_lite", "genie_tts", "qwen_tts")
GENIE_TTS_LANGUAGE_ALIASES: dict[str, str] = {
    "chinese": "Chinese",
    "english": "English",
    "japanese": "Japanese",
    "hybrid-chinese-english": "Hybrid-Chinese-English",
    "korean": "Korean",
    "auto": "auto",
}
LLM_PROVIDERS_ENV_KEY = "LLM_PROVIDERS_JSON"


class ProviderEnvPatch(BaseModel):
    name: str
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    api_format: ApiFormat | None = None


ProviderEnvPatch.model_rebuild()


def is_api_format(value: str) -> TypeGuard[ApiFormat]:
    return value in ALLOWED_API_FORMATS


def is_translate_provider(value: str) -> TypeGuard[TranslateProvider]:
    return value in TranslateProvider.__args__


def validate_translate_provider(
    env_key_name: str,
    default: TranslateProvider = "llm",
) -> TranslateProvider:
    value = os.getenv(env_key_name, default).strip().lower()
    if is_translate_provider(value):
        return value
    logger.warning(
        "Invalid {}={!r}, allowed={}, fallback={!r}", env_key_name, value, TranslateProvider.__args__, default
    )
    return default


def is_embedding_pooling_type(value: str) -> TypeGuard[EmbeddingPoolingType]:
    return value in ALLOWED_EMBEDDING_POOLING_TYPES


def validate_embedding_pooling_type(
    env_key_name: str,
    default: EmbeddingPoolingType = "mean",
) -> EmbeddingPoolingType:
    value = os.getenv(env_key_name, default).strip().lower()
    if is_embedding_pooling_type(value):
        return value
    logger.warning(
        "Invalid {}={!r}, allowed={}, fallback={!r}",
        env_key_name,
        value,
        ALLOWED_EMBEDDING_POOLING_TYPES,
        default,
    )
    return default


def validate_provider_name(value: str, available_names: set[str], env_key_name: str) -> str:
    normalized = value.strip()
    if normalized in available_names:
        return normalized
    raise ValueError(f"Invalid {env_key_name}={value!r}, available providers={sorted(available_names)}")


def validate_thinking_mode(value: str, env_key_name: str) -> ThinkingMode:
    normalized = value.strip().lower()
    if normalized in ALLOWED_THINKING_MODES:
        return cast("ThinkingMode", normalized)
    raise ValueError(f"Invalid {env_key_name}={value!r}, available thinking modes={list(ALLOWED_THINKING_MODES)}")


def is_tts_provider(value: str) -> TypeGuard[TTSProvider]:
    return value in ALLOWED_TTS_PROVIDERS


def validate_tts_provider(value: str, env_key_name: str) -> TTSProvider:
    normalized = value.strip()
    if is_tts_provider(normalized):
        return normalized
    raise ValueError(f"Invalid {env_key_name}={value!r}, available TTS providers={list(ALLOWED_TTS_PROVIDERS)}")


def validate_genie_tts_language(value: str, env_key_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""

    resolved = GENIE_TTS_LANGUAGE_ALIASES.get(normalized.lower())
    if resolved is not None:
        return resolved
    raise ValueError(
        f"Invalid {env_key_name}={value!r}, available Genie-TTS languages={list(GENIE_TTS_LANGUAGE_ALIASES.values())}"
    )


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return "None"
    if len(api_key) <= 8:
        return api_key
    return f"{api_key[:4]}...{api_key[-4:]}"


def _parse_bool_env(key: str) -> bool | None:
    value = os.environ.get(key, "").strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def _parse_int_env(key: str) -> int | None:
    raw_value = os.environ.get(key)
    if raw_value is None or not raw_value.strip():
        return None

    try:
        return int(raw_value.strip())
    except ValueError:
        logger.warning("Invalid {}={!r}, expected an integer, ignoring", key, raw_value)
        return None


def _parse_provider_env_json() -> list[ProviderEnvPatch]:
    raw_value = os.environ.get(LLM_PROVIDERS_ENV_KEY, "").strip()
    if not raw_value:
        return []

    try:
        payload: object = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {LLM_PROVIDERS_ENV_KEY}: JSON decode failed: {exc}") from exc

    items: list[object]
    if isinstance(payload, list):
        items = cast("list[object]", payload)
    elif isinstance(payload, dict):
        payload_map = cast("dict[str, object]", payload)
        providers_value = payload_map.get("providers", [])
        if not isinstance(providers_value, list):
            raise ValueError(f"Invalid {LLM_PROVIDERS_ENV_KEY}: providers must be a list")
        items = cast("list[object]", providers_value)
    else:
        raise ValueError(f"Invalid {LLM_PROVIDERS_ENV_KEY}: expected a JSON object or list")

    try:
        patches: list[ProviderEnvPatch] = []
        for item in items:
            patches.append(ProviderEnvPatch.model_validate(item))
        return patches
    except ValidationError as exc:
        raise ValueError(f"Invalid {LLM_PROVIDERS_ENV_KEY}: {exc}") from exc


def merge_provider_patches(
    current_providers: list[LLMProviderSetting],
    patches: list[ProviderEnvPatch],
) -> list[LLMProviderSetting]:
    merged = [provider.model_copy(deep=True) for provider in current_providers]
    index_by_name = {provider.name: index for index, provider in enumerate(merged)}

    for patch in patches:
        provider_name = patch.name.strip()
        if not provider_name:
            logger.warning("Skipping provider patch with blank name")
            continue

        if provider_name in index_by_name:
            target = merged[index_by_name[provider_name]]
        else:
            target = LLMProviderSetting(
                name=provider_name,
                llm_api_key="",
                llm_base_url="",
                api_format="chat_completion",
            )
            merged.append(target)
            index_by_name[provider_name] = len(merged) - 1

        if patch.llm_base_url is not None:
            target.llm_base_url = patch.llm_base_url
        if patch.llm_api_key is not None:
            target.llm_api_key = patch.llm_api_key
        if patch.api_format is not None:
            target.api_format = patch.api_format

        merged[index_by_name[provider_name]] = target

    return merged


def main() -> None:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    settings = load_settings_file("lab.toml", XnneHangLabSettings)

    provider_patches = _parse_provider_env_json()
    if provider_patches:
        settings.agent.llm.providers = merge_provider_patches(settings.agent.llm.providers, provider_patches)

    provider_names = {provider.name for provider in settings.agent.llm.providers}

    settings.agent.translate.deeplx.api_key = os.environ.get("DEEPLX_API_KEY", "")
    settings.agent.translate_provider = validate_translate_provider("TRANSLATE_PROVIDER")
    if "LLM_TRANSLATE_MODEL_PATH" in os.environ:
        settings.agent.translate.llm.model_path = os.environ.get("LLM_TRANSLATE_MODEL_PATH", "").strip()
    if (value := _parse_int_env("LLM_TRANSLATE_N_GPU_LAYERS")) is not None:
        settings.agent.translate.llm.n_gpu_layers = value

    if "CHAT_MODEL_PROVIDER" in os.environ:
        settings.agent.chat_model.llm_provider = validate_provider_name(
            os.environ.get("CHAT_MODEL_PROVIDER", ""),
            provider_names,
            "CHAT_MODEL_PROVIDER",
        )
    if "CHAT_MODEL_NAME" in os.environ:
        settings.agent.chat_model.llm_model_name = os.environ.get("CHAT_MODEL_NAME", "").strip()
    if "CHAT_MODEL_SUPPORT_VISION" in os.environ:
        settings.agent.chat_model.support_vision = (
            os.environ.get("CHAT_MODEL_SUPPORT_VISION", "false").lower() == "true"
        )
    if "CHAT_MODEL_THINKING_MODE" in os.environ:
        settings.agent.chat_model.thinking_mode = validate_thinking_mode(
            os.environ.get("CHAT_MODEL_THINKING_MODE", "default"),
            "CHAT_MODEL_THINKING_MODE",
        )

    if "VISION_MODEL_PROVIDER" in os.environ:
        settings.agent.vision_model.llm_provider = validate_provider_name(
            os.environ.get("VISION_MODEL_PROVIDER", ""),
            provider_names,
            "VISION_MODEL_PROVIDER",
        )
    if "VISION_MODEL_NAME" in os.environ:
        settings.agent.vision_model.llm_model_name = os.environ.get("VISION_MODEL_NAME", "").strip()
    if "TTS_PROVIDER" in os.environ:
        settings.agent.tts.provider = validate_tts_provider(os.environ.get("TTS_PROVIDER", ""), "TTS_PROVIDER")
    if "ASR_MODEL_PROVIDER" in os.environ:
        v = os.environ.get("ASR_MODEL_PROVIDER", "").strip()
        if v not in ("none", "sherpa", "qwen"):
            raise ValueError(f"Invalid ASR_MODEL_PROVIDER={v!r}, must be one of: none, sherpa, qwen")
        settings.asr.asr_model_provider = cast("Literal['none', 'sherpa', 'qwen']", v)
    if (value := _parse_bool_env("TTS_GSV_LITE_USE_BERT")) is not None:
        settings.agent.tts.gsv_lite.use_bert = value
    if "TTS_GENIE_TTS_LANGUAGE" in os.environ:
        settings.agent.tts.genie_tts.language = validate_genie_tts_language(
            os.environ.get("TTS_GENIE_TTS_LANGUAGE", ""),
            "TTS_GENIE_TTS_LANGUAGE",
        )
    if (value := _parse_bool_env("TTS_GENIE_TTS_USE_ROBERTA")) is not None:
        settings.agent.tts.genie_tts.use_roberta = value
    if (value := _parse_int_env("TTS_GENIE_TTS_ONNX_INTRA_THREADS")) is not None:
        settings.agent.tts.genie_tts.onnx_intra_threads = value

    if "LOCAL_EMBEDDING_MODEL_PATH" in os.environ:
        settings.local_embedding.model_path = os.environ.get("LOCAL_EMBEDDING_MODEL_PATH", "").strip()
    if "LOCAL_EMBEDDING_POOLING_TYPE" in os.environ:
        settings.local_embedding.pooling_type = validate_embedding_pooling_type("LOCAL_EMBEDDING_POOLING_TYPE")
    if (value := _parse_int_env("LOCAL_EMBEDDING_N_GPU_LAYERS")) is not None:
        settings.local_embedding.n_gpu_layers = value

    if (value := _parse_bool_env("PKG_LLM_TRANSLATE")) is not None:
        settings.package.llm_translate = value
    if (value := _parse_bool_env("PKG_LOCAL_EMBEDDING")) is not None:
        settings.package.local_embedding = value

    for provider in settings.agent.llm.providers:
        logger.info("llm.providers[{}].llm_api_key: {}", provider.name, mask_api_key(provider.llm_api_key))
        logger.info("llm.providers[{}].llm_base_url: {}", provider.name, provider.llm_base_url)
        logger.info("llm.providers[{}].api_format: {}", provider.name, provider.api_format)

    logger.info("agent.translate.deeplx.api_key: {}", mask_api_key(settings.agent.translate.deeplx.api_key))
    logger.info("agent.translate_provider: {}", settings.agent.translate_provider)
    logger.info("agent.translate.llm.model_path: {}", settings.agent.translate.llm.model_path)
    logger.info("agent.translate.llm.n_gpu_layers: {}", settings.agent.translate.llm.n_gpu_layers)
    logger.info("agent.chat_model.llm_provider: {}", settings.agent.chat_model.llm_provider)
    logger.info("agent.chat_model.llm_model_name: {}", settings.agent.chat_model.llm_model_name)
    logger.info("agent.chat_model.support_vision: {}", settings.agent.chat_model.support_vision)
    logger.info("agent.chat_model.thinking_mode: {}", settings.agent.chat_model.thinking_mode)
    logger.info("agent.vision_model.llm_provider: {}", settings.agent.vision_model.llm_provider)
    logger.info("agent.vision_model.llm_model_name: {}", settings.agent.vision_model.llm_model_name)
    logger.info("agent.tts.provider: {}", settings.agent.tts.provider)
    logger.info("agent.tts.gsv_lite.use_bert: {}", settings.agent.tts.gsv_lite.use_bert)
    logger.info("agent.tts.genie_tts.language: {}", settings.agent.tts.genie_tts.language)
    logger.info("agent.tts.genie_tts.use_roberta: {}", settings.agent.tts.genie_tts.use_roberta)
    logger.info("agent.tts.genie_tts.onnx_intra_threads: {}", settings.agent.tts.genie_tts.onnx_intra_threads)
    logger.info("local_embedding.model_path: {}", settings.local_embedding.model_path)
    logger.info("local_embedding.pooling_type: {}", settings.local_embedding.pooling_type)
    logger.info("local_embedding.n_gpu_layers: {}", settings.local_embedding.n_gpu_layers)
    logger.info("package.llm_translate: {}", settings.package.llm_translate)
    logger.info("package.local_embedding: {}", settings.package.local_embedding)
    logger.info("package.qwen_tts: {}", settings.package.qwen_tts)
    logger.info("package.gsv_lite: {}", settings.package.gsv_lite)
    logger.info("package.genie_tts: {}", settings.package.genie_tts)
    logger.info("package.sherpa_asr: {}", settings.package.sherpa_asr)
    logger.info("package.qwen_asr: {}", settings.package.qwen_asr)
    logger.info("Sync API key done!")

    write_settings_file("lab.toml", settings)


if __name__ == "__main__":
    main()
