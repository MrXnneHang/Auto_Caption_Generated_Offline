from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from lab.config_manager import XnneHangLabSettings, load_settings_file

if TYPE_CHECKING:
    from lab.asr.types import ASRResponse

Float32Array = npt.NDArray[np.float32]
DEFAULT_TOKEN_DURATION_MS = 240


def import_sherpa_onnx() -> Any:
    """导入 sherpa_onnx，并在 Windows 下补充 onnxruntime DLL 路径。

    Args:
        None.

    Returns:
        Any: 导入后的 `sherpa_onnx` 模块。

    Raises:
        ImportError: `sherpa_onnx` 未安装时抛出。
    """
    if os.name == "nt":
        try:
            import onnxruntime as ort
        except ImportError:
            ort = None

        if ort is not None:
            ort_file = getattr(ort, "__file__", None)
            if ort_file is not None:
                capi_dir = Path(ort_file).resolve().parent / "capi"
                if capi_dir.exists():
                    os.add_dll_directory(str(capi_dir))

    import sherpa_onnx

    return sherpa_onnx


def get_ffmpeg_path() -> str:
    """读取当前配置中的 ffmpeg 可执行文件路径。

    Args:
        None.

    Returns:
        str: ffmpeg 路径；配置读取失败时回退为 `ffmpeg`。

    Raises:
        None.
    """
    try:
        settings = load_settings_file("lab.toml", XnneHangLabSettings)
    except Exception:
        return "ffmpeg"
    return settings.asr.FFMPEG_PATH


def assert_file_exists(path: Path, description: str) -> None:
    """断言文件或目录存在。

    Args:
        path: 待检查路径。
        description: 路径说明文本。

    Returns:
        None.

    Raises:
        FileNotFoundError: 路径不存在时抛出。
    """
    if not path.exists():
        raise FileNotFoundError(f"{description} not found: {path}")


def find_first_existing(model_dir: Path, filenames: list[str]) -> Path | None:
    """在目录中查找首个存在的候选文件。

    Args:
        model_dir: 检索目录。
        filenames: 候选文件名列表。

    Returns:
        Path | None: 命中的文件路径；未命中时返回 `None`。

    Raises:
        None.
    """
    for filename in filenames:
        candidate = model_dir / filename
        if candidate.exists():
            return candidate
    return None


def decode_audio(audio_path: Path, sample_rate: int = 16000) -> tuple[Float32Array, int]:
    """使用 ffmpeg 将音频解码为单声道 float32 PCM。

    Args:
        audio_path: 输入音频文件路径。
        sample_rate: 目标采样率，默认 16000。

    Returns:
        tuple[Float32Array, int]: 解码后的采样数组与采样率。

    Raises:
        RuntimeError: ffmpeg 解码失败或解码结果为空时抛出。
    """
    command = [
        get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore").strip() or "ffmpeg decode failed")

    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if samples.size == 0:
        raise RuntimeError(f"Decoded audio is empty: {audio_path}")

    return np.ascontiguousarray(samples), sample_rate


def build_asr_response(audio_path: Path, result: Any) -> ASRResponse:
    """将 sherpa-onnx 原始 ASR 结果转换为标准 ASRResponse。

    Args:
        audio_path: 输入音频路径。
        result: sherpa-onnx 返回的结果对象。

    Returns:
        ASRResponse: 兼容现有 server/client 的响应结构。

    Raises:
        None.
    """
    tokens: list[str] = [token for token in list(getattr(result, "tokens", [])) if token]
    timestamps: list[float] = list(getattr(result, "timestamps", []))
    timestamps_ms = [int(t * 1000) for t in timestamps]
    timestamp_pairs: list[list[int]] = []

    for index, start in enumerate(timestamps_ms):
        inferred_end = start + DEFAULT_TOKEN_DURATION_MS
        if index + 1 < len(timestamps_ms):
            end = min(inferred_end, timestamps_ms[index + 1])
        else:
            end = inferred_end
        timestamp_pairs.append([start, end])

    if not tokens:
        raw_text = (getattr(result, "text", "") or "").strip()
        tokens = [token for token in raw_text.split(" ") if token]

    pair_count = min(len(tokens), len(timestamp_pairs))
    tokens = tokens[:pair_count]
    timestamp_pairs = timestamp_pairs[:pair_count]

    response: ASRResponse = {
        "key": audio_path.stem,
        "text": " ".join(tokens),
        "timestamp": timestamp_pairs,
    }
    return response


def create_vad_config(sherpa_onnx: Any, vad_model_path: Path, sample_rate: int) -> Any:
    """构造 silero-vad 配置对象。

    Args:
        sherpa_onnx: 已导入的 `sherpa_onnx` 模块。
        vad_model_path: VAD 模型文件路径。
        sample_rate: 音频采样率。

    Returns:
        Any: `VadModelConfig` 实例。

    Raises:
        None.
    """
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(vad_model_path)
    config.silero_vad.threshold = 0.5

    try:
        settings = load_settings_file("lab.toml", XnneHangLabSettings)
        sherpa_settings = settings.asr.sherpa
        config.silero_vad.min_silence_duration = sherpa_settings.vad_min_silence_duration
        config.silero_vad.min_speech_duration = sherpa_settings.vad_min_speech_duration
        config.silero_vad.max_speech_duration = sherpa_settings.vad_max_speech_duration
    except Exception:
        config.silero_vad.min_silence_duration = 0.25
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.max_speech_duration = 8.0

    config.sample_rate = sample_rate
    return config


def collect_vad_timestamps(vad: Any, samples: Float32Array, sample_rate: int, window_size: int) -> list[list[int]]:
    """执行一次完整的 VAD 推理并提取毫秒级时间段。

    Args:
        vad: `VoiceActivityDetector` 实例。
        samples: 解码后的音频采样。
        sample_rate: 音频采样率。
        window_size: VAD 滑窗大小。

    Returns:
        list[list[int]]: `[[start, end], ...]` 形式的语音段列表。

    Raises:
        None.
    """
    offset = 0
    timestamps: list[list[int]] = []

    while offset + window_size <= len(samples):
        vad.accept_waveform(samples[offset : offset + window_size])
        offset += window_size
        timestamps.extend(pop_vad_segments(vad, sample_rate))

    if offset < len(samples):
        vad.accept_waveform(samples[offset:])

    vad.flush()
    timestamps.extend(pop_vad_segments(vad, sample_rate))
    return timestamps


def pop_vad_segments(vad: Any, sample_rate: int) -> list[list[int]]:
    """从 detector 队列中提取已完成语音段。

    Args:
        vad: `VoiceActivityDetector` 实例。
        sample_rate: 音频采样率。

    Returns:
        list[list[int]]: 以毫秒表示的语音段列表。

    Raises:
        None.
    """
    timestamps: list[list[int]] = []

    while not vad.empty():
        segment = vad.front
        start_sample = int(segment.start)
        end_sample = start_sample + len(segment.samples)
        timestamps.append(
            [
                int(start_sample * 1000 / sample_rate),
                int(end_sample * 1000 / sample_rate),
            ]
        )
        vad.pop()

    return timestamps
