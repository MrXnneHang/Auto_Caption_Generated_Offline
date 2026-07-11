from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

_N_FFT = 400
_HOP = 160
_N_MELS = 128
_DEFAULT_N_SAMPLES = 480_000
_DEFAULT_NB_FRAMES = 3000
_HANN_WINDOW = np.hanning(_N_FFT + 1)[:-1].astype(np.float32)

_MEL_FILTERS: np.ndarray | None = None
_MEL_FILTERS_PATH: Path | None = None


def _load_mel_filters(model_dir: Path | None = None) -> np.ndarray:
    global _MEL_FILTERS, _MEL_FILTERS_PATH

    if _MEL_FILTERS is not None and _MEL_FILTERS_PATH is not None:
        return _MEL_FILTERS

    candidates: list[Path] = []
    if model_dir is not None:
        candidates.extend([model_dir / "mel_filters.npy", model_dir.parent / "mel_filters.npy"])

    for candidate in candidates:
        if not candidate.exists():
            continue

        raw = np.load(str(candidate))
        if raw.shape == (_N_MELS, _N_FFT // 2 + 1):
            filters = raw.astype(np.float32)
        elif raw.shape == (_N_FFT // 2 + 1, _N_MELS):
            filters = raw.T.astype(np.float32)
        else:
            raise ValueError(f"Unexpected mel_filters.npy shape: {raw.shape}")

        _MEL_FILTERS = filters
        _MEL_FILTERS_PATH = candidate
        return filters

    raise FileNotFoundError("mel_filters.npy was not found in the OpenVINO model directory.")


def _build_byte_decoder() -> dict[str, int]:
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("\xa1"), ord("\xac") + 1))
        + list(range(ord("\xae"), ord("\xff") + 1))
    )
    cs = list(bs)
    n = 0
    for value in range(256):
        if value not in bs:
            bs.append(value)
            cs.append(256 + n)
            n += 1
    return {chr(codepoint): value for value, codepoint in zip(bs, cs, strict=True)}


_BYTE_DECODER = _build_byte_decoder()


def _bpe_decode(token_strings: list[str]) -> str:
    merged = "".join(token_strings)
    byte_values: list[int] = []

    for char in merged:
        value = _BYTE_DECODER.get(char)
        if value is not None:
            byte_values.append(value)

    try:
        return bytes(byte_values).decode("utf-8", errors="replace")
    except Exception:
        return merged


class LightProcessor:
    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        _load_mel_filters(model_dir)

        with (model_dir / "prompt_template.json").open("r", encoding="utf-8") as file:
            template = json.load(file)

        self._prefix_ids: list[int] = list(template["prefix_ids"])
        self._suffix_ids: list[int] = list(template["suffix_ids"])
        self._n_audio_tokens: int = int(template["n_audio_tokens"])
        self.pad_id: int = int(template["audio_pad_id"])
        self.eos_id: int = int(template["eos_id"])
        self.eot_id: int = int(template["eot_id"])
        self._special_ids: set[int] = {int(token_id) for token_id in template["special_ids"]}
        self._n_samples: int = int(template.get("n_samples", _DEFAULT_N_SAMPLES))
        self._nb_frames: int = int(template.get("nb_frames", _DEFAULT_NB_FRAMES))
        self._language_suffix_ids: dict[str, list[int]] = {
            str(language): [int(token_id) for token_id in token_ids]
            for language, token_ids in template.get("language_suffix_ids", {}).items()
        }
        self.supported_languages: list[str] = list(
            template.get("supported_languages", list(self._language_suffix_ids.keys()))
        )

        self._prefix_sys_head = self._prefix_ids[:3]
        self._prefix_sys_tail = self._prefix_ids[3:]

        with (model_dir / "vocab.json").open("r", encoding="utf-8") as file:
            vocab: dict[str, int] = json.load(file)
        self._id_to_token: dict[int, str] = {token_id: token for token, token_id in vocab.items()}

        with (model_dir / "tokenizer_config.json").open("r", encoding="utf-8") as file:
            tokenizer_config = json.load(file)
        for token_id, info in tokenizer_config.get("added_tokens_decoder", {}).items():
            self._id_to_token[int(token_id)] = str(info["content"])

        self._bpe_tokenizer: object | None = None

    @property
    def max_audio_ms(self) -> int:
        return int(round(self._n_samples * 1000 / 16_000))

    def _get_bpe_tokenizer(self) -> object:
        if self._bpe_tokenizer is not None:
            return self._bpe_tokenizer

        try:
            from tokenizers import Tokenizer
            from tokenizers.models import BPE
            from tokenizers.pre_tokenizers import ByteLevel
        except ImportError as exc:
            raise RuntimeError("The `tokenizers` package is required for Qwen-ASR context hints.") from exc

        model = BPE.from_file(
            str(self._model_dir / "vocab.json"),
            str(self._model_dir / "merges.txt"),
            unk_token="<|endoftext|>",
        )
        tokenizer = Tokenizer(model)
        tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)
        self._bpe_tokenizer = tokenizer
        return tokenizer

    def encode_text(self, text: str) -> list[int]:
        tokenizer = cast("Any", self._get_bpe_tokenizer())
        encoding = tokenizer.encode(text)
        return cast("list[int]", list(encoding.ids))

    def _extract_mel(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio, got shape {audio.shape}")

        if len(audio) > self._n_samples:
            audio = audio[: self._n_samples]
        elif len(audio) < self._n_samples:
            audio = np.pad(audio, (0, self._n_samples - len(audio)))

        half_window = _N_FFT // 2
        centered_audio = np.pad(audio, half_window, mode="reflect")
        frames = np.lib.stride_tricks.sliding_window_view(centered_audio, _N_FFT)[::_HOP]
        frames = frames[: self._nb_frames].astype(np.float32)
        windowed = frames * _HANN_WINDOW

        stft = np.fft.rfft(windowed, axis=1)
        power = np.abs(stft).astype(np.float32) ** 2
        mel = _load_mel_filters(self._model_dir) @ power.T

        log_mel = np.log10(np.maximum(mel, 1e-10))
        log_mel = np.maximum(log_mel, log_mel.max() - 8.0)
        log_mel = (log_mel + 4.0) / 4.0
        return log_mel[np.newaxis, :, :].astype(np.float32)

    def prepare(
        self,
        audio: np.ndarray,
        language: str | None = None,
        context: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        mel = self._extract_mel(audio)

        if context and context.strip():
            context_ids = self.encode_text(context.strip())
            prefix_ids = self._prefix_sys_head + context_ids + self._prefix_sys_tail
        else:
            prefix_ids = self._prefix_ids

        if language and language in self._language_suffix_ids:
            suffix_ids = self._suffix_ids + self._language_suffix_ids[language]
        else:
            suffix_ids = self._suffix_ids

        input_ids = np.array(
            prefix_ids + [self.pad_id] * self._n_audio_tokens + suffix_ids,
            dtype=np.int64,
        )[np.newaxis, :]
        return mel, input_ids

    def decode(self, token_ids: list[int], skip_special: bool = True) -> str:
        token_strings: list[str] = []
        for token_id in token_ids:
            if skip_special and token_id in self._special_ids:
                continue
            token = self._id_to_token.get(token_id)
            if token:
                token_strings.append(token)
        return _bpe_decode(token_strings)
