from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

from loguru import logger

from lab.asr.sherpa.engine import (
    get_sherpa_asr,
    get_sherpa_vad,
    load_sherpa_asr as load_sherpa_asr_engine,
    load_sherpa_vad,
    reset_sherpa_engines,
)
from lab.config_manager import XnneHangLabSettings, load_settings_file

logger = cast("Any", logger)


def load_sherpa_asr() -> None:
    """预加载 Sherpa-ONNX Paraformer ASR 与 VAD 引擎。

    Args:
        None.

    Returns:
        None.

    Raises:
        FileNotFoundError: sherpa-onnx 模型路径不存在时抛出。
    """
    lab_settings = load_settings_file("lab.toml", XnneHangLabSettings)
    sherpa_settings = lab_settings.asr.sherpa

    load_sherpa_asr_engine(
        model_dir=Path(sherpa_settings.asr_model_dir),
        num_threads=sherpa_settings.num_threads,
    )
    load_sherpa_vad(vad_model_path=Path(lab_settings.asr.vad_model_path))


def sherpa_asr_audio(input_path: Path) -> dict[str, Any]:
    """执行 Sherpa-ONNX Paraformer ASR 推理。

    Args:
        input_path: 输入音频文件路径。

    Returns:
        dict[str, Any]: 包含 key、text、timestamp、process_time 的结果字典。

    Raises:
        FileNotFoundError: 音频文件不存在时抛出。
        RuntimeError: sherpa-onnx 推理失败时抛出。
    """
    start = time.perf_counter()
    response = get_sherpa_asr().transcribe(input_path)
    process_time = time.perf_counter() - start
    logger.info(f"Sherpa-ASR inference completed in {process_time:.3f}s text={response['key']}")

    return {
        "key": response["key"],
        "text": response["text"],
        "timestamp": response["timestamp"],
        "process_time": process_time,
    }


def sherpa_vad_audio(input_path: Path) -> dict[str, Any]:
    """执行 Sherpa-ONNX VAD 检测。

    Args:
        input_path: 输入音频文件路径。

    Returns:
        dict[str, Any]: 包含 key、timestamp、audio_length、process_time 的结果字典。

    Raises:
        FileNotFoundError: 音频文件不存在时抛出。
        RuntimeError: sherpa-onnx VAD 推理失败时抛出。
    """
    start = time.perf_counter()
    response = get_sherpa_vad().detect(input_path)
    process_time = time.perf_counter() - start

    return {
        "key": response["key"],
        "timestamp": response["timestamp"],
        "audio_length": response["audio_length"],
        "process_time": process_time,
    }


def reload_sherpa_asr() -> None:
    """重新加载 Sherpa-ONNX Paraformer ASR 与 VAD 引擎。

    Args:
        None.

    Returns:
        None.

    Raises:
        FileNotFoundError: sherpa-onnx 模型路径不存在时抛出。
    """
    reset_sherpa_engines()
    load_sherpa_asr()
