from __future__ import annotations

import asyncio
import json
import random
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from loguru import logger

from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.utils.stream_audio import AudioPayload, prepare_audio_payload

if TYPE_CHECKING:
    from lab.agent.output_types import Actions, DisplayText
    from lab.config_manager.vtuber import CharacterSettings
    from lab.conversations.types import WebSocketSend
    from lab.live2d_model import Live2dModel


_NON_SPOKEN_TTS_RE = re.compile(r'[\s.,!?，。！？\'"』」）】()\[\]{}…\-\n\r\t]+')
_TOOL_STATUS_DISPLAY_RE = re.compile(r"\[\s*🔧[^\]]*]")
_TOOL_STATUS_XML_RE = re.compile(r"<tool>.*?</tool>", re.DOTALL)
TTS_GENERATION_TIMEOUT_S = 8.0
_SUPPORTED_TTS_PROVIDERS = frozenset({"gsv_lite", "genie_tts", "qwen_tts"})
_VOICE_AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".opus", ".flac", ".ogg")
_GSV_LITE_REQUEST_PARAM_KEYS = frozenset(
    {"top_k", "top_p", "temperature", "repetition_penalty", "noise_scale", "speed"}
)
PLAYBACK_ACK_GRACE_S = 5.0
PLAYBACK_ACK_MIN_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class VoiceConfigData:
    workspace_root: Path
    voice_id: str
    asset_bundle: str
    config_path: Path
    default_emotion: str = "default"
    selection: str | None = None
    preferred_engine: str | None = None
    engine_params: dict[str, dict[str, object]] | None = None
    emotions: dict[str, VoiceEmotionData] | None = None


@dataclass(frozen=True)
class VoiceClipData:
    clip_id: str
    ref_audio: str
    ref_text: str | None = None
    ref_text_file: str | None = None
    speaker_audio: str | None = None


@dataclass(frozen=True)
class VoiceEmotionData:
    default_clip: str | None = None
    speaker_audio: str | None = None
    clips: list[VoiceClipData] | None = None


@dataclass(frozen=True)
class ResolvedTTSDispatch:
    engine: str
    request_payload: dict[str, Any]


def _summarize_text(text: str | None, *, limit: int = 48) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def has_audible_tts_text(tts_text: str) -> bool:
    """Return True only when the text has something worth translating or speaking."""
    normalized = (tts_text or "").replace("*", "")
    normalized = _TOOL_STATUS_XML_RE.sub("", normalized)
    normalized = _TOOL_STATUS_DISPLAY_RE.sub("", normalized)
    return len(_NON_SPOKEN_TTS_RE.sub("", normalized)) > 0


def _normalize_tts_provider(tts_provider: str | None) -> str:
    return (tts_provider or "genie_tts").strip().lower() or "genie_tts"


def _normalize_optional_tts_provider(tts_provider: str | None) -> str | None:
    normalized = (tts_provider or "").strip().lower()
    if not normalized:
        return None
    if normalized not in _SUPPORTED_TTS_PROVIDERS:
        raise ValueError(f"Unsupported TTS provider: {tts_provider}")
    return normalized


def _get_tts_provider_label(tts_provider: str | None) -> str:
    provider = _normalize_tts_provider(tts_provider)
    labels = {
        "genie_tts": "Genie-TTS",
        "gsv_lite": "GSV-Lite",
        "qwen_tts": "Qwen-TTS",
    }
    return labels.get(provider, provider)


def _iter_reference_base_dirs(character_name: str, tts_provider: str | None) -> list[Path]:
    provider = _normalize_tts_provider(tts_provider)
    provider_dirs = {
        "genie_tts": [Path("models/genie-tts") / character_name],
        "gsv_lite": [Path("models/gsv-tts-lite") / character_name],
        "qwen_tts": [
            Path("models/genie-tts") / character_name,
            Path("models/gsv-tts-lite") / character_name,
        ],
    }

    bases: list[Path] = []
    for base in provider_dirs.get(provider, []):
        if base in bases:
            continue
        bases.append(base)
    return bases


def _resolve_ref_audio_and_text(
    character_config: CharacterSettings | None,
    emotion_keys: list[str] | None,
    *,
    tts_provider: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve ref_audio and optional ref_text from the current character TTS config."""

    if character_config is None:
        return None, None

    tts_cfg = character_config.tts_config
    if not tts_cfg.character_name:
        return None, None

    emotions = tts_cfg.emotions
    if not emotions:
        logger.error(
            "No {} emotions configured for character: {}",
            _get_tts_provider_label(tts_provider),
            tts_cfg.character_name,
        )
        return None, None

    candidates = [key for key in emotion_keys or [] if key]

    for key in candidates:
        emotion = emotions.get(key)
        if emotion is None or not emotion.path:
            continue
        for base in _iter_reference_base_dirs(tts_cfg.character_name, tts_provider):
            candidate = base / emotion.path
            if candidate.is_file():
                return str(candidate), (emotion.ref_text or None)

    first_emotion = next(iter(emotions.values()), None)
    if first_emotion is not None and first_emotion.path:
        for base in _iter_reference_base_dirs(tts_cfg.character_name, tts_provider):
            candidate = base / first_emotion.path
            if candidate.is_file():
                return str(candidate), (first_emotion.ref_text or None)

    return None, None


def _require_ref_audio_and_text(
    character_config: CharacterSettings | None,
    emotion_keys: list[str] | None,
    *,
    tts_provider: str | None = None,
) -> tuple[str, str | None]:
    """Resolve ref_audio and fail fast when the configured file is missing."""

    provider_label = _get_tts_provider_label(tts_provider)
    resolved_ref_audio_path, resolved_ref_text = _resolve_ref_audio_and_text(
        character_config,
        emotion_keys,
        tts_provider=tts_provider,
    )
    if resolved_ref_audio_path is not None:
        return resolved_ref_audio_path, resolved_ref_text

    if character_config is None:
        raise ValueError(f"{provider_label} ref audio is not configured: character_config is missing")

    tts_cfg = character_config.tts_config
    if not tts_cfg.character_name:
        raise ValueError(f"{provider_label} ref audio is not configured: character_name is empty")

    emotions = tts_cfg.emotions
    if not emotions:
        raise ValueError(f"{provider_label} ref audio is not configured for character: {tts_cfg.character_name}")

    candidate_keys = [key for key in emotion_keys or [] if key]
    checked_paths: list[Path] = []

    for key in candidate_keys:
        emotion = emotions.get(key)
        if emotion is None or not emotion.path:
            continue
        for base in _iter_reference_base_dirs(tts_cfg.character_name, tts_provider):
            candidate = base / emotion.path
            checked_paths.append(candidate)
            if candidate.is_file():
                return str(candidate), (emotion.ref_text or None)

    first_emotion = next(iter(emotions.values()), None)
    if first_emotion is not None and first_emotion.path:
        for base in _iter_reference_base_dirs(tts_cfg.character_name, tts_provider):
            candidate = base / first_emotion.path
            if candidate not in checked_paths:
                checked_paths.append(candidate)
            if candidate.is_file():
                return str(candidate), (first_emotion.ref_text or None)

    if checked_paths:
        checked = ", ".join(str(path) for path in checked_paths)
        raise FileNotFoundError(
            f"{provider_label} ref audio does not exist for character '{tts_cfg.character_name}'. Checked: {checked}"
        )

    raise ValueError(f"{provider_label} ref audio is not configured for character: {tts_cfg.character_name}")


def _resolve_gsv_lite_speaker_audio_path(
    character_config: CharacterSettings | None,
    emotion_keys: list[str] | None,
    *,
    tts_provider: str | None = "gsv_lite",
) -> str | None:
    """Resolve optional speaker_audio for GSV-Lite timbre reference."""

    if character_config is None:
        return None

    tts_cfg = character_config.tts_config
    if not tts_cfg.character_name:
        return None

    emotions = tts_cfg.emotions
    if not emotions:
        return None

    candidate_keys = [key for key in emotion_keys or [] if key]
    keys_to_try: list[str] = []

    for key in candidate_keys:
        if key in emotions and key not in keys_to_try:
            keys_to_try.append(key)

    if "default" in emotions and "default" not in keys_to_try:
        keys_to_try.append("default")

    first_key = next(iter(emotions), None)
    if first_key is not None and first_key not in keys_to_try:
        keys_to_try.append(first_key)

    checked_paths: list[Path] = []
    for key in keys_to_try:
        speaker_audio_path = emotions[key].speaker_audio_path.strip()
        if not speaker_audio_path:
            continue
        for base in _iter_reference_base_dirs(tts_cfg.character_name, tts_provider):
            candidate = base / speaker_audio_path
            checked_paths.append(candidate)
            if candidate.is_file():
                return str(candidate)

    if checked_paths:
        checked = ", ".join(str(path) for path in checked_paths)
        raise FileNotFoundError(
            f"GSV-Lite speaker audio does not exist for character '{tts_cfg.character_name}'. Checked: {checked}"
        )

    return None


def _resolve_workspace_root(lab_settings: object | None) -> Path:
    root = getattr(getattr(lab_settings, "root", None), "root_dir", "")
    normalized_root = str(root).strip()
    if normalized_root:
        return Path(normalized_root).resolve()
    return Path.cwd().resolve()


def _resolve_voice_assets_root(lab_settings: object | None, workspace_root: Path) -> Path:
    agent_tts_settings = getattr(getattr(lab_settings, "agent", None), "tts", None)
    raw_path = getattr(agent_tts_settings, "voice_assets_root", "./voices")
    normalized = str(raw_path).strip() or "./voices"
    path = Path(normalized)
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()


def _to_workspace_relative_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _find_audio_file(directory: Path, stem: str) -> Path | None:
    if not stem or not directory.is_dir():
        return None

    for extension in _VOICE_AUDIO_EXTENSIONS:
        candidate = directory / f"{stem}{extension}"
        if candidate.is_file():
            return candidate

    candidates = sorted(
        entry
        for entry in directory.iterdir()
        if entry.is_file() and entry.stem == stem and entry.suffix.lower() in _VOICE_AUDIO_EXTENSIONS
    )
    return candidates[0] if candidates else None


def _find_first_audio_file(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None

    candidates = sorted(
        entry for entry in directory.iterdir() if entry.is_file() and entry.suffix.lower() in _VOICE_AUDIO_EXTENSIONS
    )
    return candidates[0] if candidates else None


def _list_audio_stems(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []

    stems: list[str] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in _VOICE_AUDIO_EXTENSIONS:
            continue
        if entry.stem not in stems:
            stems.append(entry.stem)
    return stems


def _list_nested_audio_dirs(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []

    names: list[str] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        if _find_first_audio_file(entry) is None:
            continue
        names.append(entry.name)
    return names


def _read_ref_text(text_path: Path) -> str | None:
    if not text_path.is_file():
        return None
    content = text_path.read_text(encoding="utf-8").strip()
    return content or None


def _resolve_named_audio_with_text(directory: Path, name: str) -> tuple[Path | None, str | None]:
    direct_audio = _find_audio_file(directory, name)
    if direct_audio is not None:
        return direct_audio, _read_ref_text(directory / f"{name}.txt")

    nested_dir = directory / name
    nested_audio = _find_first_audio_file(nested_dir)
    if nested_audio is None:
        return None, None

    return nested_audio, _read_ref_text(nested_audio.with_suffix(".txt"))


def _list_named_audio_keys(directory: Path) -> list[str]:
    keys: list[str] = []
    for key in _list_audio_stems(directory):
        if key not in keys:
            keys.append(key)
    for key in _list_nested_audio_dirs(directory):
        if key not in keys:
            keys.append(key)
    return keys


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized


def _normalize_optional_selection(value: object) -> str | None:
    normalized = _normalize_optional_string(value)
    if normalized is None:
        return None

    resolved = normalized.lower()
    if resolved not in {"random", "first"}:
        raise ValueError(f"Unsupported voice clip selection: {normalized}")

    return resolved


def _normalize_string_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None

    raw_mapping = cast("Mapping[object, object]", value)
    return {str(key): item for key, item in raw_mapping.items()}


def _normalize_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None

    return cast("list[object]", value)


def _parse_voice_emotions(payload: Mapping[str, object]) -> dict[str, VoiceEmotionData] | None:
    emotions_section = _normalize_string_object_dict(payload.get("emotions"))
    if emotions_section is None:
        return None

    parsed: dict[str, VoiceEmotionData] = {}
    for raw_emotion_name, raw_emotion_value in emotions_section.items():
        emotion_name = raw_emotion_name.strip()
        emotion_payload = _normalize_string_object_dict(raw_emotion_value)
        if not emotion_name or emotion_payload is None:
            continue

        default_clip = _normalize_optional_string(emotion_payload.get("default_clip"))
        speaker_audio = _normalize_optional_string(emotion_payload.get("speaker_audio"))
        clips: list[VoiceClipData] = []

        raw_clips = _normalize_object_list(emotion_payload.get("clips"))
        if raw_clips is not None:
            for index, raw_clip in enumerate(raw_clips, start=1):
                clip_payload = _normalize_string_object_dict(raw_clip)
                if clip_payload is None:
                    continue
                ref_audio = _normalize_optional_string(clip_payload.get("ref_audio"))
                if ref_audio is None:
                    continue
                clip_id = _normalize_optional_string(clip_payload.get("id")) or str(index)
                clips.append(
                    VoiceClipData(
                        clip_id=clip_id,
                        ref_audio=ref_audio,
                        ref_text=_normalize_optional_string(clip_payload.get("ref_text")),
                        ref_text_file=_normalize_optional_string(clip_payload.get("ref_text_file")),
                        speaker_audio=_normalize_optional_string(clip_payload.get("speaker_audio")),
                    )
                )

        if not clips:
            ref_audio = _normalize_optional_string(emotion_payload.get("ref_audio"))
            if ref_audio is not None:
                clips.append(
                    VoiceClipData(
                        clip_id="1",
                        ref_audio=ref_audio,
                        ref_text=_normalize_optional_string(emotion_payload.get("ref_text")),
                        ref_text_file=_normalize_optional_string(emotion_payload.get("ref_text_file")),
                        speaker_audio=_normalize_optional_string(emotion_payload.get("speaker_audio")),
                    )
                )

        if not clips:
            continue

        parsed[emotion_name] = VoiceEmotionData(
            default_clip=default_clip,
            speaker_audio=speaker_audio,
            clips=clips,
        )

    return parsed or None


def _dedupe_nonempty(values: list[str | None]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = (value or "").strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _resolve_voice_explicit_ref_text(voice_asset_dir: Path, clip: VoiceClipData) -> str | None:
    if clip.ref_text is not None:
        return clip.ref_text

    if clip.ref_text_file is not None:
        return _read_ref_text(voice_asset_dir / clip.ref_text_file)

    return _read_ref_text((voice_asset_dir / clip.ref_audio).with_suffix(".txt"))


def _pick_voice_emotion(
    emotions: dict[str, VoiceEmotionData],
    emotion_keys: list[str] | None,
    default_emotion: str,
) -> tuple[str, VoiceEmotionData] | None:
    candidates = _dedupe_nonempty([*(emotion_keys or []), default_emotion, "default"])
    for emotion in candidates:
        emotion_config = emotions.get(emotion)
        if emotion_config is not None:
            return emotion, emotion_config

    first_key = next(iter(emotions), None)
    if first_key is None:
        return None
    return first_key, emotions[first_key]


def _pick_voice_clip(voice_config: VoiceConfigData, emotion: VoiceEmotionData) -> VoiceClipData | None:
    clips = emotion.clips or []
    if not clips:
        return None

    if emotion.default_clip is not None:
        for clip in clips:
            if clip.clip_id == emotion.default_clip:
                return clip

    if len(clips) == 1:
        return clips[0]

    if voice_config.selection == "first":
        return clips[0]

    return random.choice(clips)


def _resolve_voice_from_config(
    voice_config: VoiceConfigData,
    voice_assets_root: Path,
    emotion_keys: list[str] | None,
) -> tuple[str | None, str | None, str | None]:
    if not voice_config.emotions:
        return None, None, None

    selected = _pick_voice_emotion(voice_config.emotions, emotion_keys, voice_config.default_emotion)
    if selected is None:
        return None, None, None

    matched_emotion, emotion_config = selected
    clip = _pick_voice_clip(voice_config, emotion_config)
    if clip is None:
        return None, None, None

    voice_asset_dir = voice_assets_root / voice_config.asset_bundle
    ref_audio_path = voice_asset_dir / clip.ref_audio
    if not ref_audio_path.is_file():
        raise FileNotFoundError(
            f"Voice ref audio does not exist for voice '{voice_config.voice_id}' emotion '{matched_emotion}': {ref_audio_path}"
        )

    speaker_audio_path: Path | None = None
    raw_speaker_audio = clip.speaker_audio or emotion_config.speaker_audio
    if raw_speaker_audio is not None:
        speaker_audio_path = voice_asset_dir / raw_speaker_audio
        if not speaker_audio_path.is_file():
            raise FileNotFoundError(
                f"Voice speaker audio does not exist for voice '{voice_config.voice_id}' emotion '{matched_emotion}': {speaker_audio_path}"
            )

    return (
        _to_workspace_relative_path(ref_audio_path, voice_config.workspace_root),
        _resolve_voice_explicit_ref_text(voice_asset_dir, clip),
        _to_workspace_relative_path(speaker_audio_path, voice_config.workspace_root)
        if speaker_audio_path is not None
        else None,
    )


def _load_voice_config(voice_id: str, workspace_root: Path) -> VoiceConfigData | None:
    voice_id = voice_id.strip()
    if not voice_id:
        return None

    voice_config_path = workspace_root / "config" / "voices" / f"{voice_id}.toml"
    if not voice_config_path.is_file():
        return None

    default_emotion = "default"
    selection: str | None = None
    preferred_engine: str | None = None
    engine_params: dict[str, dict[str, object]] = {}
    asset_bundle = voice_id

    with voice_config_path.open("rb") as file:
        payload = cast("dict[str, object]", tomllib.load(file))

    voice_section = _normalize_string_object_dict(payload.get("voice"))
    if voice_section is not None:
        raw_asset_bundle = voice_section.get("asset_bundle")
        if isinstance(raw_asset_bundle, str) and raw_asset_bundle.strip():
            asset_bundle = raw_asset_bundle.strip()

        raw_default_emotion = voice_section.get("default_emotion")
        if isinstance(raw_default_emotion, str) and raw_default_emotion.strip():
            default_emotion = raw_default_emotion.strip()

        selection = _normalize_optional_selection(voice_section.get("selection"))

        raw_preferred_engine = voice_section.get("preferred_engine")
        if raw_preferred_engine is not None:
            preferred_engine = _normalize_optional_tts_provider(str(raw_preferred_engine))

    engine_params_section = _normalize_string_object_dict(payload.get("engine_params"))
    if engine_params_section is not None:
        for raw_engine, params in engine_params_section.items():
            normalized_engine = _normalize_optional_tts_provider(raw_engine)
            params_payload = _normalize_string_object_dict(params)
            if normalized_engine is None or params_payload is None:
                continue
            engine_params[normalized_engine] = params_payload

    emotions = _parse_voice_emotions(payload)

    return VoiceConfigData(
        workspace_root=workspace_root,
        voice_id=voice_id,
        asset_bundle=asset_bundle,
        config_path=voice_config_path,
        default_emotion=default_emotion,
        selection=selection,
        preferred_engine=preferred_engine,
        engine_params=engine_params,
        emotions=emotions,
    )


def _resolve_voice_ref_audio_and_text(
    voice_config: VoiceConfigData | None,
    voice_assets_root: Path,
    emotion_keys: list[str] | None,
) -> tuple[str | None, str | None, str | None]:
    if voice_config is None:
        return None, None, None

    configured_ref_audio, configured_ref_text, configured_speaker_audio = _resolve_voice_from_config(
        voice_config,
        voice_assets_root,
        emotion_keys,
    )
    if configured_ref_audio is not None:
        return configured_ref_audio, configured_ref_text, configured_speaker_audio

    voice_asset_dir = voice_assets_root / voice_config.asset_bundle
    emotion_dirs: list[Path] = []
    for candidate in (voice_asset_dir / "emotions", voice_asset_dir):
        if candidate.is_dir() and candidate not in emotion_dirs:
            emotion_dirs.append(candidate)
    if not emotion_dirs:
        return None, None, None

    emotion_candidates = _dedupe_nonempty([*(emotion_keys or []), voice_config.default_emotion, "default"])

    matched_emotion: str | None = None
    ref_audio_path: Path | None = None
    ref_text: str | None = None
    for emotion in emotion_candidates:
        for emotions_dir in emotion_dirs:
            candidate, candidate_ref_text = _resolve_named_audio_with_text(emotions_dir, emotion)
            if candidate is None:
                continue
            matched_emotion = emotion
            ref_audio_path = candidate
            ref_text = candidate_ref_text
            break
        if ref_audio_path is not None:
            break

    if ref_audio_path is None:
        available_emotions: list[str] = []
        for emotions_dir in emotion_dirs:
            for emotion in _list_named_audio_keys(emotions_dir):
                if emotion not in available_emotions:
                    available_emotions.append(emotion)
        if not available_emotions:
            return None, None, None
        matched_emotion = available_emotions[0]
        for emotions_dir in emotion_dirs:
            candidate, candidate_ref_text = _resolve_named_audio_with_text(emotions_dir, matched_emotion)
            if candidate is None:
                continue
            ref_audio_path = candidate
            ref_text = candidate_ref_text
            break

    if ref_audio_path is None or matched_emotion is None:
        return None, None, None

    speaker_audio: Path | None = None
    speaker_dir = voice_asset_dir / "speaker"
    if speaker_dir.is_dir():
        speaker_candidates = _dedupe_nonempty([matched_emotion, voice_config.default_emotion, "default"])
        for emotion in speaker_candidates:
            speaker_audio, _ = _resolve_named_audio_with_text(speaker_dir, emotion)
            if speaker_audio is not None:
                break

    return (
        _to_workspace_relative_path(ref_audio_path, voice_config.workspace_root),
        ref_text,
        _to_workspace_relative_path(speaker_audio, voice_config.workspace_root) if speaker_audio is not None else None,
    )


def _require_voice_ref_audio_and_text(
    voice_config: VoiceConfigData | None,
    voice_assets_root: Path,
    emotion_keys: list[str] | None,
) -> tuple[str, str | None, str | None]:
    """Resolve voice assets and fail fast instead of falling back to profile emotions."""

    if voice_config is None:
        raise ValueError("TTS voice is not configured")

    ref_audio, ref_text, speaker_audio = _resolve_voice_ref_audio_and_text(
        voice_config,
        voice_assets_root,
        emotion_keys,
    )
    if ref_audio is not None:
        return ref_audio, ref_text, speaker_audio

    voice_asset_dir = voice_assets_root / voice_config.asset_bundle
    raise FileNotFoundError(f"Voice ref audio does not exist for voice '{voice_config.voice_id}': {voice_asset_dir}")


def resolve_voice_assets(
    lab_settings: object | None,
    voice_id: str,
    emotion_keys: list[str] | None = None,
) -> tuple[Path, str | None, Path | None]:
    """Resolve voice ref/speaker audio to absolute workspace paths."""

    workspace_root = _resolve_workspace_root(lab_settings)
    voice_assets_root = _resolve_voice_assets_root(lab_settings, workspace_root)
    voice_config = _load_voice_config(voice_id, workspace_root)
    if voice_config is None:
        raise FileNotFoundError(
            f"Voice config does not exist for '{voice_id}': {workspace_root / 'config' / 'voices' / f'{voice_id}.toml'}"
        )

    ref_audio_path, ref_text, speaker_audio_path = _require_voice_ref_audio_and_text(
        voice_config,
        voice_assets_root,
        emotion_keys,
    )
    resolved_ref_audio = (workspace_root / ref_audio_path).resolve()
    resolved_speaker_audio = (workspace_root / speaker_audio_path).resolve() if speaker_audio_path else None
    return resolved_ref_audio, ref_text, resolved_speaker_audio


class TTSDispatcher:
    """Resolve engine and voice resources before calling concrete TTS clients."""

    def __init__(self, lab_settings: object, character_config: CharacterSettings | None) -> None:
        self._lab_settings = lab_settings
        self._character_config = character_config
        self._workspace_root = _resolve_workspace_root(lab_settings)
        self._voice_assets_root = _resolve_voice_assets_root(lab_settings, self._workspace_root)
        agent_tts_settings = getattr(getattr(self._lab_settings, "agent", None), "tts", None)
        self._voice_config = (
            None
            if _normalize_tts_provider(getattr(agent_tts_settings, "provider", None)) == "none"
            else _load_voice_config(self._configured_voice_id, self._workspace_root)
        )
        if (
            self._configured_voice_id
            and self._voice_config is None
            and _normalize_tts_provider(getattr(agent_tts_settings, "provider", None)) != "none"
        ):
            raise FileNotFoundError(
                f"Voice config does not exist for configured voice '{self._configured_voice_id}': "
                f"{self._workspace_root / 'config' / 'voices' / f'{self._configured_voice_id}.toml'}"
            )

    @property
    def _character_name(self) -> str:
        if self._character_config is None:
            return ""
        return self._character_config.tts_config.character_name.strip()

    @property
    def _configured_voice_id(self) -> str:
        if self._character_config is None:
            return ""

        voice = (self._character_config.tts_config.voice or "").strip()
        return voice

    def resolve(self, text: str, emotion_keys: list[str] | None = None) -> ResolvedTTSDispatch:
        engine = self._resolve_engine()
        if engine == "none":
            return ResolvedTTSDispatch(engine="none", request_payload={})
        ref_audio_path, ref_text, speaker_audio_path = self._resolve_resources(engine, emotion_keys)
        request_payload: dict[str, Any] = {
            "text": text,
            "ref_audio_path": ref_audio_path,
            "ref_text": ref_text,
        }
        if engine == "gsv_lite":
            request_payload["speaker_audio_path"] = speaker_audio_path
            request_payload.update(self._resolve_gsv_lite_engine_params())
        return ResolvedTTSDispatch(engine=engine, request_payload=request_payload)

    def _resolve_engine(self) -> str:
        agent_tts_settings = getattr(getattr(self._lab_settings, "agent", None), "tts", None)
        configured_provider = _normalize_tts_provider(getattr(agent_tts_settings, "provider", None))
        if configured_provider == "none":
            return "none"

        if self._character_config is not None:
            profile_engine = _normalize_optional_tts_provider(self._character_config.tts_config.engine)
            if profile_engine is not None:
                return profile_engine

        if self._voice_config is not None and self._voice_config.preferred_engine is not None:
            return self._voice_config.preferred_engine

        return configured_provider

    def _resolve_resources(self, engine: str, emotion_keys: list[str] | None) -> tuple[str, str | None, str | None]:
        if self._voice_config is not None:
            return _require_voice_ref_audio_and_text(
                self._voice_config,
                self._voice_assets_root,
                emotion_keys,
            )

        ref_audio_path, ref_text = _require_ref_audio_and_text(
            self._character_config,
            emotion_keys,
            tts_provider=engine,
        )
        speaker_audio_path: str | None = None
        if engine == "gsv_lite":
            speaker_audio_path = _resolve_gsv_lite_speaker_audio_path(
                self._character_config,
                emotion_keys,
                tts_provider=engine,
            )
        return ref_audio_path, ref_text, speaker_audio_path

    def _resolve_gsv_lite_engine_params(self) -> dict[str, Any]:
        if self._voice_config is None or not self._voice_config.engine_params:
            return {}

        raw_params = self._voice_config.engine_params.get("gsv_lite", {})
        return {key: value for key, value in raw_params.items() if key in _GSV_LITE_REQUEST_PARAM_KEYS}


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation"""

    def __init__(self, turn_id: str | None = None, lab_setting: XnneHangLabSettings | None = None) -> None:
        self.task_list: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()
        self._tts_semaphore = asyncio.Semaphore(1)
        self._payload_queue: asyncio.Queue[tuple[AudioPayload, int]] = asyncio.Queue()
        self._sender_task: asyncio.Task[None] | None = None
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        self._turn_id = turn_id
        self._lab_setting = lab_setting
        self._estimated_playback_seconds = 0.0

    def has_output(self) -> bool:
        """Return True when this turn queued any display or audio payload."""
        return self._sequence_counter > 0

    def playback_completion_timeout_s(self) -> float:
        """Return a bounded wait budget for frontend playback completion ACK."""
        return max(
            PLAYBACK_ACK_MIN_TIMEOUT_S,
            self._estimated_playback_seconds + PLAYBACK_ACK_GRACE_S,
        )

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Actions | None,
        live2d_model: Live2dModel | None,
        websocket_send: WebSocketSend,
        character_config: CharacterSettings | None = None,
    ) -> None:
        """
        Queue a TTS task while maintaining order of delivery.

        Args:
            tts_text: Text to synthesize
            display_text: Text to display in UI
            actions: Live2D model actions
            live2d_model: Live2D model instance
            websocket_send: WebSocket send function
            character_config: Current runtime character configuration
        """
        if self._lab_setting is not None and self._lab_setting.agent.tts.provider == "none":
            current_sequence = self._sequence_counter
            self._sequence_counter += 1
            if self._sender_task is None or self._sender_task.done():
                self._sender_task = asyncio.create_task(self._process_payload_queue(websocket_send))
            await self._send_silent_payload(display_text, actions, current_sequence)
            return

        if not has_audible_tts_text(tts_text):
            logger.debug("Empty TTS text, sending silent display payload")
            current_sequence = self._sequence_counter
            self._sequence_counter += 1

            if self._sender_task is None or self._sender_task.done():
                self._sender_task = asyncio.create_task(self._process_payload_queue(websocket_send))

            await self._send_silent_payload(display_text, actions, current_sequence)
            return

        current_sequence = self._sequence_counter
        self._sequence_counter += 1

        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._process_payload_queue(websocket_send))

        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                character_config=character_config,
                sequence_number=current_sequence,
            )
        )
        self.task_list.append(task)

    async def _process_payload_queue(self, websocket_send: WebSocketSend) -> None:
        """Process and send payloads in correct order."""
        buffered_payloads: dict[int, AudioPayload] = {}
        logger.debug("Starting TTS payload sender task...")

        while True:
            payload, sequence_number = await self._payload_queue.get()
            sequence_number = int(sequence_number)
            buffered_payloads[sequence_number] = payload

            if sequence_number != self._next_sequence_to_send:
                logger.debug(
                    "[TTS_SEND] payload ready but waiting for earlier seq: ready_seq={} next_seq={} text={}",
                    sequence_number,
                    self._next_sequence_to_send,
                    _summarize_text(payload.get("display_text", {}).get("text")),
                )

            while self._next_sequence_to_send in buffered_payloads:
                next_payload = buffered_payloads.pop(self._next_sequence_to_send)
                display_text = next_payload.get("display_text", {})
                logger.debug(
                    "[TTS_SEND] payload sent seq={} has_audio={} text={}",
                    self._next_sequence_to_send,
                    bool(next_payload.get("audio")),
                    _summarize_text(display_text.get("text")),
                )
                await websocket_send(json.dumps(next_payload))
                self._next_sequence_to_send += 1

            self._payload_queue.task_done()

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Actions | None,
        sequence_number: int,
        *,
        tts_error: bool = False,
    ) -> None:
        """Queue a silent audio payload."""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
            turn_id=self._turn_id,
            tts_error=tts_error,
        )
        await self._payload_queue.put((audio_payload, sequence_number))

    def _accumulate_expected_playback(self, payload: AudioPayload) -> None:
        if not payload.get("audio"):
            return

        slice_length = payload.get("slice_length") or 0
        volumes = payload.get("volumes") or []
        if slice_length <= 0 or not volumes:
            return

        self._estimated_playback_seconds += (len(volumes) * slice_length) / 1000.0

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Actions | None,
        live2d_model: Live2dModel | None,
        character_config: CharacterSettings | None,
        sequence_number: int,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery."""
        del live2d_model
        async with self._tts_semaphore:
            tts_emotion_keys = [actions.tts_emotion_key] if actions is not None and actions.tts_emotion_key else None
            audio_file_path = await self._generate_audio(
                tts_text,
                character_config=character_config,
                emotion_keys=tts_emotion_keys,
            )
            if not audio_file_path:
                logger.warning(
                    "[TTS_READY] skipping audio payload because synthesis failed seq={} text={}",
                    sequence_number,
                    _summarize_text(display_text.text),
                )
                await self._send_silent_payload(display_text, actions, sequence_number, tts_error=True)
                return
            payload = prepare_audio_payload(
                audio_path=str(audio_file_path),
                display_text=display_text,
                actions=actions,
                turn_id=self._turn_id,
            )
            self._accumulate_expected_playback(payload)
            logger.debug(
                "[TTS_READY] audio ready seq={} text={}",
                sequence_number,
                _summarize_text(display_text.text),
            )
            await self._payload_queue.put((payload, sequence_number))

    async def _generate_audio(
        self,
        text: str,
        character_config: CharacterSettings | None = None,
        emotion_keys: list[str] | None = None,
    ) -> Path | None:
        """Generate audio file from text."""
        provider: str | None = None
        try:
            lab_settings = self._lab_setting or load_settings_file("lab.toml", XnneHangLabSettings)
            dispatch = TTSDispatcher(lab_settings, character_config).resolve(text, emotion_keys)
            if dispatch.engine == "none":
                return None
            provider = dispatch.engine
            cache_dir = _resolve_workspace_root(lab_settings) / "cache" / "tts"
            cache_dir.mkdir(parents=True, exist_ok=True)
            if provider == "gsv_lite":
                from lab.api.clients import GSVLiteClient, GSVLiteRequest

                gsv_lite_client = GSVLiteClient()
                response = await asyncio.wait_for(
                    gsv_lite_client.asyncpost(GSVLiteRequest(**dispatch.request_payload)),
                    timeout=TTS_GENERATION_TIMEOUT_S,
                )
                if response is None:
                    logger.error(
                        "Failed to get a valid response from GSV-Lite client: {}",
                        gsv_lite_client.last_error or "unknown error",
                    )
                    return None
            elif provider == "genie_tts":
                from lab.api.clients import GenieTTSClient, GenieTTSRequest

                genie_tts_client = GenieTTSClient()
                response = await asyncio.wait_for(
                    genie_tts_client.asyncpost(GenieTTSRequest(**dispatch.request_payload)),
                    timeout=TTS_GENERATION_TIMEOUT_S,
                )
                if response is None:
                    logger.error(
                        "Failed to get a valid response from Genie-TTS client: {}",
                        genie_tts_client.last_error or "unknown error",
                    )
                    return None
            elif provider == "qwen_tts":
                from lab.api.clients import QwenTTSClient, QwenTTSRequest

                qwen_tts_client = QwenTTSClient()
                response = await asyncio.wait_for(
                    qwen_tts_client.asyncpost(QwenTTSRequest(**dispatch.request_payload)),
                    timeout=TTS_GENERATION_TIMEOUT_S,
                )
                if response is None:
                    logger.error(
                        "Failed to get a valid response from Qwen-TTS client: {}",
                        qwen_tts_client.last_error or "unknown error",
                    )
                    return None
            else:
                logger.error(f"Unsupported TTS provider: {provider}")
                return None
            audio_path = (
                cache_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}.{response['audio_type']}"
            )
            with audio_path.open("wb") as f:
                f.write(response["audio_byte"])
            return Path(audio_path)
        except TimeoutError:
            if provider == "genie_tts":
                try:
                    from lab.api.logic.genie_tts import stop_genie_tts_synthesis

                    stop_genie_tts_synthesis()
                except Exception as exc:
                    logger.warning("Failed to stop timed-out Genie-TTS synthesis: {}", exc)
            logger.warning(
                "TTS generation timed out after {}s, degrading to silent payload: {}",
                TTS_GENERATION_TIMEOUT_S,
                _summarize_text(text),
            )
            return None
        except Exception as e:
            logger.error(f"Error generating audio: {e}", exc_info=True)
            return None

    async def wait_until_all_payloads_sent(self) -> None:
        """Wait until all queued TTS work has been converted and sent to the frontend."""
        if self.task_list:
            await asyncio.gather(*self.task_list)
        if self._sender_task is not None:
            await self._payload_queue.join()

    def clear(self) -> None:
        """Clear all pending tasks and reset state."""
        for task in self.task_list:
            if not task.done():
                task.cancel()
        self.task_list.clear()
        if self._sender_task:
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        self._estimated_playback_seconds = 0.0
        logger.debug("Clearing TTS payload queue...")
        self._payload_queue = asyncio.Queue()
