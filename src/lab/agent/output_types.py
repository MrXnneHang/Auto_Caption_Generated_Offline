from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, Field, field_validator, model_validator


class IdleClipPayload(BaseModel):
    id: str | None = None
    url: str
    weight: float | None = Field(default=None, ge=0)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idle clip url must not be empty")
        return normalized


class IdleBankPayload(BaseModel):
    clips: list[IdleClipPayload]
    mode: Literal["random", "random_no_repeat"] | None = None

    @model_validator(mode="after")
    def validate_clips(self) -> IdleBankPayload:
        if not self.clips:
            raise ValueError("idle bank must contain at least one clip")
        return self


class IdlePlayPayload(BaseModel):
    id: str | None = None
    url: str | None = None

    @field_validator("id", "url")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target(self) -> IdlePlayPayload:
        if not self.id and not self.url:
            raise ValueError("idle_play requires id or url")
        return self


class IdleClipDict(TypedDict, total=False):
    id: str
    url: str
    weight: float


class IdleBankDict(TypedDict, total=False):
    clips: list[IdleClipDict]
    mode: Literal["random", "random_no_repeat"]


class IdlePlayDict(TypedDict, total=False):
    id: str
    url: str


def _coerce_idle_bank(value: Any) -> IdleBankPayload | None:
    if value is None:
        return None
    if isinstance(value, IdleBankPayload):
        return value
    if isinstance(value, dict):
        return IdleBankPayload.model_validate(value)
    raise TypeError(f"idle_bank must be IdleBankPayload or dict, got {type(value)}")


def _coerce_idle_play(value: Any) -> IdlePlayPayload | None:
    if value is None:
        return None
    if isinstance(value, IdlePlayPayload):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if "/" in normalized or "\\" in normalized or "." in normalized:
            return IdlePlayPayload(url=normalized)
        return IdlePlayPayload(id=normalized)
    if isinstance(value, dict):
        return IdlePlayPayload.model_validate(value)
    raise TypeError(f"idle_play must be IdlePlayPayload, str, or dict, got {type(value)}")


class ActionsDict(TypedDict):
    expressions: list[str] | list[int] | None
    pictures: list[str] | None
    sounds: list[str] | None
    emotion_keys: list[str] | None
    expression_emotion_key: str | None
    tts_emotion_key: str | None
    pose: dict[str, float] | None
    pose_patch: dict[str, float] | None
    pose_mode: str | None
    pose_weight: float | None
    mixer_weights: dict[str, float] | None
    mixer_weights_mode: str | None
    idle_list: list[str] | None
    idle_mode: str | None
    idle_bank: IdleBankDict | None
    idle_play: IdlePlayDict | None


@dataclass
class Actions:
    """Represents actions that can be performed alongside text output"""

    expressions: list[str] | list[int] | None = None
    pictures: list[str] | None = None
    sounds: list[str] | None = None
    emotion_keys: list[str] | None = None
    expression_emotion_key: str | None = None
    tts_emotion_key: str | None = None
    pose: dict[str, float] | None = None
    pose_patch: dict[str, float] | None = None
    pose_mode: str | None = None
    pose_weight: float | None = None
    mixer_weights: dict[str, float] | None = None
    mixer_weights_mode: str | None = None
    idle_list: list[str] | None = None
    idle_mode: str | None = None
    idle_bank: IdleBankPayload | None = None
    idle_play: IdlePlayPayload | None = None

    def __post_init__(self) -> None:
        self.idle_bank = _coerce_idle_bank(self.idle_bank)
        self.idle_play = _coerce_idle_play(self.idle_play)

    def to_dict(self) -> ActionsDict:
        """Convert Actions object to a dictionary for JSON serialization"""
        return ActionsDict(
            expressions=self.expressions,
            pictures=self.pictures,
            sounds=self.sounds,
            emotion_keys=self.emotion_keys,
            expression_emotion_key=self.expression_emotion_key,
            tts_emotion_key=self.tts_emotion_key,
            pose=self.pose,
            pose_patch=self.pose_patch,
            pose_mode=self.pose_mode,
            pose_weight=self.pose_weight,
            mixer_weights=self.mixer_weights,
            mixer_weights_mode=self.mixer_weights_mode,
            idle_list=self.idle_list,
            idle_mode=self.idle_mode,
            idle_bank=cast("IdleBankDict", self.idle_bank.model_dump(exclude_none=True)) if self.idle_bank else None,
            idle_play=cast("IdlePlayDict", self.idle_play.model_dump(exclude_none=True)) if self.idle_play else None,
        )


class BaseOutput(ABC):
    """Base class for agent outputs that can be iterated"""

    @abstractmethod
    def __aiter__(self):
        """Make the output iterable"""
        pass


class DisplayTextDict(TypedDict):
    text: str
    name: str | None
    avatar: str | None


@dataclass
class DisplayText:
    """Text to be displayed with optional metadata"""

    text: str
    name: str | None = "AI"  # Keep the name field for frontend display
    avatar: str | None = None

    def to_dict(self) -> DisplayTextDict:
        """Convert to dictionary for JSON serialization"""
        return DisplayTextDict(text=self.text, name=self.name, avatar=self.avatar)

    def __str__(self) -> str:
        """String representation for logging"""
        return f"{self.name}: {self.text}"


@dataclass
class SentenceOutput(BaseOutput):
    """
    Output type for text-based responses.
    Contains a single sentence pair (display and TTS) with associated actions.

    Attributes:
        display_text: Text to be displayed in UI
        tts_text: Text to be sent to TTS engine
        actions: Associated actions (expressions, pictures, sounds)
    """

    display_text: DisplayText  # Changed from str to DisplayText
    tts_text: str  # Text for TTS
    actions: Actions

    async def __aiter__(self):
        """Yield the sentence pair and actions"""
        yield self.display_text, self.tts_text, self.actions


@dataclass
class ToolCallEvent:
    """Structured tool call event that passes through the transformer pipeline unchanged."""

    tool_id: str
    tool_name: str
    args: str
    status: str
    result: str | None = None


@dataclass
class AudioOutput(BaseOutput):
    """Output type for audio-based responses"""

    audio_path: str
    display_text: DisplayText  # Changed from str to DisplayText
    transcript: str  # Original transcript
    actions: Actions

    async def __aiter__(self):
        """Iterate through audio segments and their actions"""
        yield self.audio_path, self.display_text, self.transcript, self.actions
