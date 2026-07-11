from __future__ import annotations

import asyncio
import base64
import gc
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import soundfile as sf
from fastapi import HTTPException
from loguru import logger
from numpy.typing import NDArray

from lab.config_manager import XnneHangLabSettings, load_settings_file

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from lab.config_manager.qwen_tts import QwenTTSModelName

DEFAULT_SAMPLE_RATE = 24000  # https://github.com/andimarafioti/faster-qwen3-tts/issues/50
DEFAULT_MODEL_SOURCES = {
    "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
}

Float32Array = NDArray[np.float32]

_tts_logger = logger.bind(group="tts")
_qwen_tts_engine: Any | None = None
_loaded_model_name: QwenTTSModelName | None = None
_loaded_model_source: str | None = None
_sample_rate: int = DEFAULT_SAMPLE_RATE
_model_lock = threading.Lock()


def _get_qwen_tts_settings() -> XnneHangLabSettings:
    return load_settings_file("lab.toml", XnneHangLabSettings)


def normalize_qwen_tts_model_name(model_name: str) -> QwenTTSModelName:
    normalized = model_name.strip().lower()
    aliases = {
        "0.6b": "0.6b",
        "0.6": "0.6b",
        "qwen3-tts-12hz-0.6b-base": "0.6b",
        "qwen/qwen3-tts-12hz-0.6b-base": "0.6b",
        "1.7b": "1.7b",
        "1.7": "1.7b",
        "qwen3-tts-12hz-1.7b-base": "1.7b",
        "qwen/qwen3-tts-12hz-1.7b-base": "1.7b",
    }
    resolved = aliases.get(normalized)
    if resolved is None:
        raise RuntimeError(f"Unsupported Qwen-TTS model: {model_name}")
    return cast("QwenTTSModelName", resolved)


def get_configured_qwen_tts_model_name(settings: XnneHangLabSettings | None = None) -> QwenTTSModelName:
    return (settings or _get_qwen_tts_settings()).agent.qwen_tts.model_name


def get_qwen_tts_model_path(model_name: QwenTTSModelName, settings: XnneHangLabSettings | None = None) -> str:
    qwen_tts_settings = (settings or _get_qwen_tts_settings()).agent.qwen_tts
    if model_name == "0.6b":
        return qwen_tts_settings.model_0_6b_path
    return qwen_tts_settings.model_1_7b_path


def _resolve_model_source(model_name: QwenTTSModelName, settings: XnneHangLabSettings) -> str:
    configured_path = get_qwen_tts_model_path(model_name, settings).strip()
    if configured_path:
        resolved_path = Path(configured_path)
        if not resolved_path.is_absolute():
            resolved_path = Path(settings.root.root_dir) / resolved_path
        if not resolved_path.exists():
            raise FileNotFoundError(f"Qwen-TTS model path does not exist for model '{model_name}': {resolved_path}")
        return str(resolved_path.resolve())

    legacy_env_model = os.environ.get("XNNEHANG_QWEN_TTS_MODEL", "").strip()
    if legacy_env_model:
        return legacy_env_model

    return DEFAULT_MODEL_SOURCES[model_name]


def _resolve_device(settings: XnneHangLabSettings | None = None) -> str:
    if device := os.environ.get("XNNEHANG_QWEN_TTS_DEVICE", "").strip():
        return device
    if settings is not None and settings.agent.qwen_tts.device.strip():
        return settings.agent.qwen_tts.device.strip()

    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _release_engine() -> None:
    global _qwen_tts_engine, _loaded_model_name, _loaded_model_source

    old_engine = _qwen_tts_engine
    _qwen_tts_engine = None
    _loaded_model_name = None
    _loaded_model_source = None
    if old_engine is not None:
        del old_engine

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            ipc_collect = getattr(torch.cuda, "ipc_collect", None)
            if callable(ipc_collect):
                ipc_collect()
    except Exception:
        pass


def get_qwen_tts_status() -> dict[str, Any]:
    settings = _get_qwen_tts_settings()
    configured_model = get_configured_qwen_tts_model_name(settings)
    return {
        "loaded": _qwen_tts_engine is not None,
        "configured_model": configured_model,
        "loaded_model": _loaded_model_name,
        "loaded_model_matches_config": _qwen_tts_engine is not None and _loaded_model_name == configured_model,
        "loaded_model_source": _loaded_model_source,
        "sample_rate": _sample_rate,
        "device": _resolve_device(settings),
    }


def load_qwen_tts_model(
    model_name: QwenTTSModelName | None = None,
    *,
    force_reload: bool = False,
) -> dict[str, Any]:
    global _qwen_tts_engine, _loaded_model_name, _loaded_model_source, _sample_rate

    settings = _get_qwen_tts_settings()
    if settings.agent.tts.provider != "qwen_tts":
        raise RuntimeError("Qwen-TTS is disabled in lab.toml")

    target_model = model_name or get_configured_qwen_tts_model_name(settings)

    with _model_lock:
        if _qwen_tts_engine is not None and _loaded_model_name == target_model and not force_reload:
            return get_qwen_tts_status()
        if _qwen_tts_engine is not None:
            _tts_logger.info(
                f"releasing qwen-tts engine before loading model={target_model} (current={_loaded_model_name})"
            )
            _release_engine()

        try:
            from faster_qwen3_tts import FasterQwen3TTS
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("faster-qwen3-tts is not installed") from exc

        model_source = _resolve_model_source(target_model, settings)
        device = _resolve_device(settings)
        _tts_logger.info(f"qwen-tts load start: model={target_model}, source={model_source}, device={device}")

        kwargs: dict[str, Any] = {"device": device}
        if device == "cuda":
            try:
                import torch

                kwargs["dtype"] = torch.bfloat16
            except Exception:
                pass

        _qwen_tts_engine = FasterQwen3TTS.from_pretrained(model_source, **kwargs)

        warmup_fn = getattr(_qwen_tts_engine, "_warmup", None)
        if settings.agent.qwen_tts.warmup_cuda_graphs and device == "cuda" and callable(warmup_fn):
            try:
                _tts_logger.info("warming up qwen-tts model (cuda graphs)...")
                warmup_fn(prefill_len=100)
                _tts_logger.info("qwen-tts warmup done")
            except Exception:
                _tts_logger.warning("qwen-tts warmup failed, continue without warmup")

        _sample_rate = DEFAULT_SAMPLE_RATE
        _loaded_model_name = target_model
        _loaded_model_source = model_source
        _tts_logger.info(f"qwen-tts load complete: model={target_model}, sample_rate={_sample_rate}")

    return get_qwen_tts_status()


def init_qwen_tts_model() -> None:
    load_qwen_tts_model()


def reload_qwen_tts_model(model_name: QwenTTSModelName | None = None) -> dict[str, Any]:
    return load_qwen_tts_model(model_name=model_name, force_reload=True)


def get_qwen_tts_model() -> Any:
    settings = _get_qwen_tts_settings()
    if settings.agent.tts.provider != "qwen_tts":
        raise HTTPException(status_code=503, detail="Qwen-TTS is disabled in lab.toml")

    configured_model = get_configured_qwen_tts_model_name(settings)
    if _qwen_tts_engine is None:
        raise HTTPException(
            status_code=503,
            detail=f"Qwen-TTS model '{configured_model}' is not loaded. Call /tts/qwen-tts/load first.",
        )

    if _loaded_model_name != configured_model:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Configured Qwen-TTS model '{configured_model}' is not loaded. "
                f"Currently loaded model: '{_loaded_model_name}'. "
                "Call /tts/qwen-tts/load or /tts/qwen-tts/reload."
            ),
        )

    return _qwen_tts_engine


def get_sample_rate() -> int:
    return _sample_rate


def _as_float32_mono_array(value: Any) -> Float32Array:
    arr = np.asarray(value, dtype=np.float32).squeeze()
    return arr


def _empty_float32() -> Float32Array:
    return np.zeros(0, dtype=np.float32)


def _to_wav_chunk(pcm: Float32Array, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, pcm, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _to_wav_b64(pcm: Float32Array, sample_rate: int) -> str:
    wav_bytes = _to_wav_chunk(pcm, sample_rate)
    return base64.b64encode(wav_bytes).decode("utf-8")


def _concat_audio(audio_list: Any) -> Float32Array:
    if isinstance(audio_list, np.ndarray):
        return _as_float32_mono_array(audio_list)

    parts: list[Float32Array] = []
    try:
        for chunk in audio_list:
            arr = _as_float32_mono_array(chunk)
            if arr.size > 0:
                parts.append(arr)
    except TypeError:
        arr = _as_float32_mono_array(audio_list)
        if arr.size > 0:
            parts.append(arr)

    if not parts:
        return _empty_float32()

    return np.concatenate(parts)


def _to_wav_bytes(pcm: Float32Array, sample_rate: int) -> bytes:
    return _to_wav_chunk(pcm, sample_rate)


def _resolve_ref(ref_audio: Path | None, ref_text: str | None) -> tuple[str | None, str]:
    ref_audio_str = str(ref_audio) if ref_audio is not None else None
    return ref_audio_str, ref_text or ""


def synthesize_once(*, text: str, ref_audio: Path | None, ref_text: str | None) -> bytes:
    model = get_qwen_tts_model()
    ref_audio_str, ref_text_str = _resolve_ref(ref_audio, ref_text)

    with _model_lock:
        result: Any = model.generate_voice_clone(
            text=text,
            language="Auto",
            ref_audio=ref_audio_str,
            ref_text=ref_text_str,
        )

    audio_arrays, sample_rate = cast("tuple[Any, Any]", result)

    audio = _concat_audio(audio_arrays)
    if audio.size == 0:
        audio = np.zeros(1, dtype=np.float32)

    sr = int(sample_rate) if isinstance(sample_rate, (int, float)) else get_sample_rate()
    return _to_wav_bytes(audio, sr)


async def synthesize_stream(
    *,
    text: str,
    ref_audio: Path | None,
    ref_text: str | None,
    chunk_size: int = 8,
) -> AsyncIterator[str]:
    model = get_qwen_tts_model()
    ref_audio_str, ref_text_str = _resolve_ref(ref_audio, ref_text)

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _run_inference() -> None:
        try:
            t0 = time.perf_counter()
            total_audio_s = 0.0
            total_gen_ms = 0.0
            ttfa_ms: float | None = None
            voice_clone_ms = 0.0

            with _model_lock:
                gen: Any = model.generate_voice_clone_streaming(
                    text=text,
                    language="Auto",
                    ref_audio=ref_audio_str,
                    ref_text=ref_text_str,
                    chunk_size=chunk_size,
                    non_streaming_mode=False,
                )

                first_audio: Any = next(gen, None)
                if first_audio is not None:
                    first_audio_tuple = cast("tuple[Any, Any, Any]", first_audio)
                    raw_audio_chunk, sr_raw, timing_raw = first_audio_tuple

                    sr = int(sr_raw) if isinstance(sr_raw, (int, float)) else get_sample_rate()
                    timing = cast("dict[str, Any]", timing_raw)

                    wall_first_ms = (time.perf_counter() - t0) * 1000.0
                    model_ms = float(timing.get("prefill_ms", 0.0)) + float(timing.get("decode_ms", 0.0))
                    voice_clone_ms = max(0.0, wall_first_ms - model_ms)

                    total_gen_ms += model_ms
                    if ttfa_ms is None:
                        ttfa_ms = total_gen_ms

                    audio_chunk = _concat_audio(raw_audio_chunk)
                    if audio_chunk.size > 0:
                        dur = audio_chunk.shape[0] / sr
                        total_audio_s += dur
                        rtf = total_audio_s / (total_gen_ms / 1000.0) if total_gen_ms > 0 else 0.0

                        payload = {
                            "type": "chunk",
                            "audio_b64": _to_wav_b64(audio_chunk, sr),
                            "sample_rate": sr,
                            "ttfa_ms": round(ttfa_ms),
                            "voice_clone_ms": round(voice_clone_ms),
                            "rtf": round(rtf, 3),
                            "total_audio_s": round(total_audio_s, 3),
                            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0),
                        }
                        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(payload))

                for item in gen:
                    audio_tuple = cast("tuple[Any, Any, Any]", item)
                    raw_audio_chunk, sr_raw, timing_raw = audio_tuple

                    sr = int(sr_raw) if isinstance(sr_raw, (int, float)) else get_sample_rate()
                    timing = cast("dict[str, Any]", timing_raw)

                    total_gen_ms += float(timing.get("prefill_ms", 0.0)) + float(timing.get("decode_ms", 0.0))
                    if ttfa_ms is None:
                        ttfa_ms = total_gen_ms

                    audio_chunk = _concat_audio(raw_audio_chunk)
                    if audio_chunk.size == 0:
                        continue

                    dur = audio_chunk.shape[0] / sr
                    total_audio_s += dur
                    rtf = total_audio_s / (total_gen_ms / 1000.0) if total_gen_ms > 0 else 0.0

                    payload = {
                        "type": "chunk",
                        "audio_b64": _to_wav_b64(audio_chunk, sr),
                        "sample_rate": sr,
                        "ttfa_ms": round(ttfa_ms),
                        "voice_clone_ms": round(voice_clone_ms),
                        "rtf": round(rtf, 3),
                        "total_audio_s": round(total_audio_s, 3),
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0),
                    }
                    loop.call_soon_threadsafe(queue.put_nowait, json.dumps(payload))

            final_rtf = total_audio_s / (total_gen_ms / 1000.0) if total_gen_ms > 0 else 0.0
            done_payload = {
                "type": "done",
                "ttfa_ms": round(ttfa_ms) if ttfa_ms is not None else 0,
                "voice_clone_ms": round(voice_clone_ms),
                "rtf": round(final_rtf, 3),
                "total_audio_s": round(total_audio_s, 3),
                "total_ms": round((time.perf_counter() - t0) * 1000.0),
            }
            loop.call_soon_threadsafe(queue.put_nowait, json.dumps(done_payload))

        except Exception as exc:
            _tts_logger.exception("streaming inference failed")
            err_payload = {
                "type": "error",
                "message": str(exc),
            }
            loop.call_soon_threadsafe(queue.put_nowait, json.dumps(err_payload))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_run_inference, daemon=True).start()

    while True:
        msg = await queue.get()
        if msg is None:
            break
        yield f"data: {msg}\n\n"
