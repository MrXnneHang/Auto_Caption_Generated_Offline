from __future__ import annotations

import subprocess
import time
import unicodedata
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Any, cast

import numpy as np
from loguru import logger

logger = cast("Any", logger)

_forced_aligners: dict[tuple[str, str], ForcedAlignerEngine] = {}
_TARGET_SAMPLE_RATE = 16_000
_DEFAULT_SUPPORTED_LANGUAGES = {
    "chinese",
    "english",
    "french",
    "german",
    "italian",
    "japanese",
    "korean",
    "portuguese",
    "russian",
    "spanish",
}


def _normalize_device(device: str) -> str:
    return device.strip().lower() or "cpu"


def _resolve_model_path(model_path: str) -> str:
    resolved = Path(model_path).expanduser().resolve()
    if not resolved.exists():
        raise RuntimeError(f"Qwen3-ForcedAligner model path does not exist: {resolved}")
    return str(resolved)


def _ensure_audio_tuple(audio: Path | tuple[np.ndarray, int]) -> tuple[np.ndarray, int]:
    if isinstance(audio, Path):
        from lab.config_manager import XnneHangLabSettings, load_settings_file

        settings = load_settings_file("lab.toml", XnneHangLabSettings)
        ffmpeg_path = settings.asr.FFMPEG_PATH or "ffmpeg"
        command = [
            ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(audio),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-ar",
            str(_TARGET_SAMPLE_RATE),
            "-",
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"ffmpeg was not found: {ffmpeg_path}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed to decode audio: {audio} ({stderr or 'unknown error'})") from exc

        waveform = np.frombuffer(result.stdout, dtype=np.float32)
        if waveform.size == 0:
            raise RuntimeError(f"ffmpeg returned empty audio stream: {audio}")
        return np.ascontiguousarray(waveform, dtype=np.float32), _TARGET_SAMPLE_RATE

    waveform, sample_rate = audio
    samples = np.ascontiguousarray(waveform, dtype=np.float32)
    if samples.ndim != 1:
        raise RuntimeError(f"ForcedAligner expects mono audio, got shape={samples.shape}")
    return samples, int(sample_rate)


class Qwen3ForceAlignProcessor:
    def __init__(self) -> None:
        self._ko_tokenizer: object | None = None

    def _is_kept_char(self, char: str) -> bool:
        if char == "'":
            return True
        category = unicodedata.category(char)
        return category.startswith("L") or category.startswith("N")

    def _clean_token(self, token: str) -> str:
        return "".join(char for char in token if self._is_kept_char(char))

    def _is_cjk_char(self, char: str) -> bool:
        code = ord(char)
        return (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0x20000 <= code <= 0x2A6DF
            or 0x2A700 <= code <= 0x2B73F
            or 0x2B740 <= code <= 0x2B81F
            or 0x2B820 <= code <= 0x2CEAF
            or 0xF900 <= code <= 0xFAFF
        )

    def _split_segment_with_chinese(self, segment: str) -> list[str]:
        tokens: list[str] = []
        buffer: list[str] = []

        def flush_buffer() -> None:
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()

        for char in segment:
            if self._is_cjk_char(char):
                flush_buffer()
                tokens.append(char)
            else:
                buffer.append(char)

        flush_buffer()
        return tokens

    def _tokenize_space_lang(self, text: str) -> list[str]:
        tokens: list[str] = []
        for segment in text.split():
            cleaned = self._clean_token(segment)
            if cleaned:
                tokens.extend(self._split_segment_with_chinese(cleaned))
        return tokens

    def _tokenize_japanese(self, text: str) -> list[str]:
        try:
            nagisa = import_module("nagisa")
        except ImportError as exc:
            raise RuntimeError("The `nagisa` package is required for Japanese forced alignment.") from exc

        words = cast("list[str]", nagisa.tagging(text).words)
        return [cleaned for word in words if (cleaned := self._clean_token(word))]

    def _tokenize_korean(self, text: str) -> list[str]:
        if self._ko_tokenizer is None:
            try:
                ltokenizer = import_module("soynlp.tokenizer").LTokenizer
            except ImportError:
                logger.warning("`soynlp` is not installed; falling back to space tokenization for Korean alignment.")
                return self._tokenize_space_lang(text)
            self._ko_tokenizer = ltokenizer(scores={})

        raw_tokens = cast("Any", self._ko_tokenizer).tokenize(text)
        return [cleaned for token in raw_tokens if (cleaned := self._clean_token(str(token)))]

    def fix_timestamp(self, data: np.ndarray) -> list[int]:
        values = data.tolist()
        count = len(values)
        if count == 0:
            return []

        dp = [1] * count
        parent = [-1] * count

        for index in range(1, count):
            for previous in range(index):
                if values[previous] <= values[index] and dp[previous] + 1 > dp[index]:
                    dp[index] = dp[previous] + 1
                    parent[index] = previous

        max_index = dp.index(max(dp))
        lis_indices: list[int] = []
        while max_index != -1:
            lis_indices.append(max_index)
            max_index = parent[max_index]
        lis_indices.reverse()

        is_normal = [False] * count
        for index in lis_indices:
            is_normal[index] = True

        result = values.copy()
        cursor = 0
        while cursor < count:
            if is_normal[cursor]:
                cursor += 1
                continue

            next_cursor = cursor
            while next_cursor < count and not is_normal[next_cursor]:
                next_cursor += 1

            left_value = next((result[idx] for idx in range(cursor - 1, -1, -1) if is_normal[idx]), None)
            right_value = next((result[idx] for idx in range(next_cursor, count) if is_normal[idx]), None)
            anomaly_count = next_cursor - cursor

            if anomaly_count <= 2:
                for index in range(cursor, next_cursor):
                    if left_value is None:
                        result[index] = right_value
                    elif right_value is None:
                        result[index] = left_value
                    else:
                        left_distance = index - (cursor - 1)
                        right_distance = next_cursor - index
                        result[index] = left_value if left_distance <= right_distance else right_value
            else:
                if left_value is not None and right_value is not None:
                    step = (right_value - left_value) / (anomaly_count + 1)
                    for index in range(cursor, next_cursor):
                        result[index] = left_value + step * (index - cursor + 1)
                elif left_value is not None:
                    for index in range(cursor, next_cursor):
                        result[index] = left_value
                elif right_value is not None:
                    for index in range(cursor, next_cursor):
                        result[index] = right_value

            cursor = next_cursor

        return [int(value) for value in result]

    def encode_timestamp(self, text: str, language: str) -> tuple[list[str], str]:
        normalized = language.strip().lower()
        if normalized == "japanese":
            word_list = self._tokenize_japanese(text)
        elif normalized == "korean":
            word_list = self._tokenize_korean(text)
        else:
            word_list = self._tokenize_space_lang(text)

        input_text = "<timestamp><timestamp>".join(word_list) + "<timestamp><timestamp>"
        input_text = "<|audio_start|><|audio_pad|><|audio_end|>" + input_text
        return word_list, input_text

    def parse_timestamp(self, word_list: list[str], timestamp: np.ndarray) -> list[dict[str, int | str]]:
        timestamp_fixed = self.fix_timestamp(timestamp)
        output: list[dict[str, int | str]] = []

        for index, word in enumerate(word_list):
            start_time = timestamp_fixed[index * 2]
            end_time = timestamp_fixed[index * 2 + 1]
            output.append(
                {
                    "text": word,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )

        return output


class ForcedAlignerEngine:
    def __init__(self, model_path: str, device: str = "cpu") -> None:
        self.model_path = _resolve_model_path(model_path)
        self.device = _normalize_device(device)
        self._lock = Lock()
        self._model: Any = None
        self._processor: Any = None
        self._aligner_processor = Qwen3ForceAlignProcessor()
        self._torch: Any = None
        self._timestamp_token_id = 0
        self._timestamp_segment_time = 0.0
        self._supported_languages = set(_DEFAULT_SUPPORTED_LANGUAGES)
        self.last_timing: dict[str, float | int | str] = {}
        self.load()

    def load(self) -> None:
        try:
            torch = import_module("torch")
            transformers = import_module("transformers")
            backend = import_module("qwen_asr.core.transformers_backend")
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-ForcedAligner requires `torch`, `transformers`, and `qwen-asr` to be installed."
            ) from exc

        auto_config = transformers.AutoConfig
        auto_model = transformers.AutoModel
        auto_processor = transformers.AutoProcessor
        qwen_config = backend.Qwen3ASRConfig
        qwen_model = backend.Qwen3ASRForConditionalGeneration
        qwen_processor = backend.Qwen3ASRProcessor

        auto_config.register("qwen3_asr", qwen_config)
        auto_model.register(qwen_config, qwen_model)
        auto_processor.register(qwen_config, qwen_processor)

        dtype = torch.float32
        model = auto_model.from_pretrained(
            self.model_path,
            torch_dtype=dtype,
            device_map=self.device,
        )
        processor = auto_processor.from_pretrained(self.model_path, fix_mistral_regex=True)
        self._torch = torch
        self._model = model
        self._processor = processor
        self._timestamp_token_id = int(model.config.timestamp_token_id)
        self._timestamp_segment_time = float(model.config.timestamp_segment_time)

        get_supported_languages = getattr(model, "get_support_languages", None)
        if callable(get_supported_languages):
            supported = cast("Any", get_supported_languages)()
            if supported:
                self._supported_languages = {str(item).lower() for item in supported}

    def supports_language(self, language: str) -> bool:
        return language.strip().lower() in self._supported_languages

    def align(
        self,
        audio: Path | tuple[np.ndarray, int],
        text: str,
        language: str,
    ) -> list[dict[str, float | str]]:
        if self._torch is None or self._model is None or self._processor is None:
            raise RuntimeError("Qwen3-ForcedAligner is not initialized.")
        if not text.strip():
            return []

        waveform, sample_rate = _ensure_audio_tuple(audio)
        if sample_rate != _TARGET_SAMPLE_RATE:
            raise RuntimeError(f"Qwen3-ForcedAligner expects 16kHz audio chunks. Got sample_rate={sample_rate}.")

        audio_duration_ms = int(round(len(waveform) * 1000 / sample_rate))
        wait_start = time.perf_counter()
        with self._lock:
            wait_sec = time.perf_counter() - wait_start
            infer_start = time.perf_counter()
            with self._torch.inference_mode():
                word_list, input_text = self._aligner_processor.encode_timestamp(text, language)
                if not word_list:
                    return []

                inputs = self._processor(
                    text=input_text,
                    audio=waveform,
                    return_tensors="pt",
                )
                preprocess_sec = time.perf_counter() - infer_start
                model_start = time.perf_counter()
                inputs = inputs.to(self._model.device).to(self._model.dtype)

                logits = self._model.thinker(**inputs).logits
                output_ids = logits.argmax(dim=-1)
                input_ids = inputs["input_ids"][0]
                masked_output_ids = output_ids[0][input_ids == self._timestamp_token_id]
                timestamp_ms = (masked_output_ids * self._timestamp_segment_time).to("cpu").numpy()
                model_sec = time.perf_counter() - model_start
                postprocess_start = time.perf_counter()
                timestamp_output = self._aligner_processor.parse_timestamp(word_list, timestamp_ms)
                postprocess_sec = time.perf_counter() - postprocess_start
            total_sec = time.perf_counter() - infer_start

        output: list[dict[str, float | str]] = []
        for item in timestamp_output:
            output.append(
                {
                    "text": str(item["text"]),
                    "start_time": round(float(item["start_time"]) / 1000.0, 3),
                    "end_time": round(float(item["end_time"]) / 1000.0, 3),
                }
            )
        self.last_timing = {
            "language": language,
            "audio_ms": audio_duration_ms,
            "text_len": len(text.strip()),
            "word_count": len(output),
            "lock_wait_sec": wait_sec,
            "preprocess_sec": preprocess_sec,
            "model_sec": model_sec,
            "postprocess_sec": postprocess_sec,
            "total_sec": total_sec,
        }
        return output


def load_forced_aligner(model_path: str, device: str = "cpu") -> ForcedAlignerEngine:
    resolved_model_path = _resolve_model_path(model_path)
    normalized_device = _normalize_device(device)
    cache_key = (resolved_model_path, normalized_device)
    engine = _forced_aligners.get(cache_key)
    if engine is None:
        engine = ForcedAlignerEngine(resolved_model_path, normalized_device)
        _forced_aligners[cache_key] = engine
    return engine


def get_forced_aligner(model_path: str, device: str = "cpu") -> ForcedAlignerEngine:
    resolved_model_path = _resolve_model_path(model_path)
    normalized_device = _normalize_device(device)
    cache_key = (resolved_model_path, normalized_device)
    engine = _forced_aligners.get(cache_key)
    if engine is None:
        raise RuntimeError(
            f"Qwen3-ForcedAligner is not loaded: model_path={resolved_model_path}, device={normalized_device}"
        )
    return engine


def reset_forced_aligner(model_path: str | None = None, device: str | None = None) -> None:
    if model_path is None:
        _forced_aligners.clear()
        return

    resolved_model_path = _resolve_model_path(model_path)
    normalized_device = _normalize_device(device or "cpu")
    _forced_aligners.pop((resolved_model_path, normalized_device), None)
