from __future__ import annotations

import time
from importlib import import_module
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from lab.config_manager import XnneHangLabSettings, load_settings_file

if TYPE_CHECKING:
    from pathlib import Path

    from lab.config_manager.qwen_asr import QwenASRModelName

logger = cast("Any", logger)


def _get_qwen_asr_engine_module() -> Any:
    # Delay importing the OpenVINO-backed engine until an explicit preload/transcribe path uses it.
    return import_module("lab.asr.qwen_asr.engine")


def _get_qwen_settings() -> XnneHangLabSettings:
    """读取 lab.toml 中的当前配置。

    Args:
        None.

    Returns:
        XnneHangLabSettings: 当前实验室配置。

    Raises:
        None.
    """
    return load_settings_file("lab.toml", XnneHangLabSettings)


def normalize_qwen_model_name(model_name: str) -> QwenASRModelName:
    """将路由中的模型标识归一化为内部枚举值。

    Args:
        model_name: 路由传入的模型标识。

    Returns:
        QwenASRModelName: 归一化后的模型名称。

    Raises:
        RuntimeError: 模型名称不受支持时抛出。
    """
    normalized = model_name.strip().lower()
    aliases = {
        "0.6b": "0.6b",
        "0.6": "0.6b",
        "qwen3-asr-0.6b": "0.6b",
        "1.7b": "1.7b",
        "1.7": "1.7b",
        "qwen3-asr-1.7b": "1.7b",
    }
    resolved = aliases.get(normalized)
    if resolved is None:
        raise RuntimeError(f"Unsupported Qwen3-ASR model: {model_name}")
    return cast("QwenASRModelName", resolved)


def get_qwen_model_path(model_name: QwenASRModelName, settings: XnneHangLabSettings | None = None) -> str:
    """读取指定模型的本地路径。

    Args:
        model_name: 模型规格名称。
        settings: 可选的当前配置。

    Returns:
        str: 本地模型路径。

    Raises:
        None.
    """
    qwen_settings = (settings or _get_qwen_settings()).asr.qwen_asr
    if model_name == "0.6b":
        return qwen_settings.model_0_6b_path
    return qwen_settings.model_1_7b_path


def get_preload_qwen_models(settings: XnneHangLabSettings | None = None) -> list[QwenASRModelName]:
    """读取并去重预加载模型列表。

    Args:
        settings: 可选的当前配置。

    Returns:
        list[QwenASRModelName]: 去重后的预加载模型列表。

    Raises:
        None.
    """
    qwen_settings = (settings or _get_qwen_settings()).asr.qwen_asr
    seen: set[QwenASRModelName] = set()
    models: list[QwenASRModelName] = []
    for model_name in qwen_settings.preload_models:
        if model_name not in seen:
            seen.add(model_name)
            models.append(model_name)
    return models


def load_qwen_asr_engine(model_name: QwenASRModelName) -> None:
    """预加载指定的 Qwen3-ASR 引擎。

    Args:
        model_name: 要加载的模型规格。

    Returns:
        None.

    Raises:
        RuntimeError: 模型加载失败时抛出。
    """
    settings = _get_qwen_settings()
    qwen_settings = settings.asr.qwen_asr
    model_path = get_qwen_model_path(model_name, settings)
    logger.info(
        f"Qwen3-ASR preload start: model={model_name}, device={qwen_settings.device}, "
        f"model_path={model_path}, gpu_cache_dir={qwen_settings.gpu_cache_dir or '<default>'}"
    )
    _get_qwen_asr_engine_module().load_qwen_asr(
        model_path=model_path,
        device=qwen_settings.device,
        cpu_threads=qwen_settings.cpu_threads,
        gpu_cache_dir=qwen_settings.gpu_cache_dir,
        forced_aligner_path=qwen_settings.forced_aligner_path,
        forced_aligner_device=qwen_settings.forced_aligner_device,
    )
    logger.info(f"Qwen3-ASR preload complete: model={model_name}")


def preload_configured_qwen_asr_engines() -> list[QwenASRModelName]:
    """预加载配置中声明的 Qwen3-ASR 模型。

    Args:
        None.

    Returns:
        list[QwenASRModelName]: 已触发加载的模型列表。

    Raises:
        RuntimeError: 模型加载失败时抛出。
    """
    settings = _get_qwen_settings()
    preload_models = get_preload_qwen_models(settings)
    logger.info(f"Qwen3-ASR configured preload models: {preload_models}")
    for model_name in preload_models:
        load_qwen_asr_engine(model_name)
    return preload_models


def qwen_asr_transcribe(input_path: Path, model_name: QwenASRModelName) -> dict[str, Any]:
    """执行指定模型的 Qwen3-ASR 推理。

    Args:
        input_path: 输入音频路径。
        model_name: 本次推理使用的模型规格。

    Returns:
        dict[str, Any]: 包含 key、text、timestamp、process_time 的结果。

    Raises:
        FileNotFoundError: 音频文件不存在时抛出。
        RuntimeError: 推理失败时抛出。
    """
    start = time.perf_counter()
    settings = _get_qwen_settings()
    qwen_settings = settings.asr.qwen_asr
    model_path = get_qwen_model_path(model_name, settings)

    engine = _get_qwen_asr_engine_module().load_qwen_asr(
        model_path=model_path,
        device=qwen_settings.device,
        cpu_threads=qwen_settings.cpu_threads,
        gpu_cache_dir=qwen_settings.gpu_cache_dir,
        forced_aligner_path=qwen_settings.forced_aligner_path,
        forced_aligner_device=qwen_settings.forced_aligner_device,
    )

    response = engine.transcribe(input_path)
    process_time = time.perf_counter() - start

    return {
        "key": response["key"],
        "text": response["text"],
        "timestamp": response["timestamp"],
        "process_time": process_time,
    }


def reload_qwen_asr_engine(model_name: QwenASRModelName) -> None:
    """重新加载指定的 Qwen3-ASR 引擎。

    Args:
        model_name: 要重新加载的模型规格。

    Returns:
        None.

    Raises:
        RuntimeError: 模型重新加载失败时抛出。
    """
    settings = _get_qwen_settings()
    qwen_settings = settings.asr.qwen_asr
    model_path = get_qwen_model_path(model_name, settings)
    qwen_asr_engine_module = _get_qwen_asr_engine_module()
    qwen_asr_engine_module.reset_qwen_asr_engine(
        model_path=model_path,
        device=qwen_settings.device,
        cpu_threads=qwen_settings.cpu_threads,
        gpu_cache_dir=qwen_settings.gpu_cache_dir,
        forced_aligner_path=qwen_settings.forced_aligner_path,
        forced_aligner_device=qwen_settings.forced_aligner_device,
    )
    qwen_asr_engine_module.load_qwen_asr(
        model_path=model_path,
        device=qwen_settings.device,
        cpu_threads=qwen_settings.cpu_threads,
        gpu_cache_dir=qwen_settings.gpu_cache_dir,
        forced_aligner_path=qwen_settings.forced_aligner_path,
        forced_aligner_device=qwen_settings.forced_aligner_device,
    )
