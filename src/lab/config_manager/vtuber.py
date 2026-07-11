"""VTuber 运行时配置模型。"""

from __future__ import annotations

import os
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class TTSPreprocessorConfig(BaseModel):
    """VTuber 链路内部使用的 TTS 文本预处理配置。

    Attributes:
        remove_special_char: 是否移除特殊字符。
        ignore_brackets: 是否忽略中括号内容。
        ignore_parentheses: 是否忽略圆括号内容。
        ignore_asterisks: 是否忽略星号包裹内容。
        ignore_angle_brackets: 是否忽略尖括号内容。
        ignore_urls: 是否忽略 URL 链接内容。
    """

    remove_special_char: Annotated[bool, Field(True)]
    ignore_brackets: Annotated[bool, Field(True)]
    ignore_parentheses: Annotated[bool, Field(True)]
    ignore_asterisks: Annotated[bool, Field(True)]
    ignore_angle_brackets: Annotated[bool, Field(True)]
    ignore_urls: Annotated[bool, Field(True)]


class TTSEmotionConfig(BaseModel):
    """单个情绪参考音频配置。

    Attributes:
        path: 相对于角色模型目录的参考音频路径。
        ref_text: 参考音频对应的参考文本。
    """

    path: Annotated[str, Field("")]
    ref_text: Annotated[str, Field("")]
    speaker_audio_path: Annotated[str, Field("")]

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_value(cls, value: object) -> object:
        """兼容旧版字符串格式的 emotion 配置。

        Args:
            value: 原始配置值，可能是字符串、字典或 `None`。

        Returns:
            归一化后的 emotion 配置值。
        """
        if isinstance(value, str):
            return {"path": value, "ref_text": "", "speaker_audio_path": ""}
        if value is None:
            return {"path": "", "ref_text": "", "speaker_audio_path": ""}
        return value


class TTSConfig(BaseModel):
    """运行时使用的角色 TTS 配置。"""

    character_name: Annotated[str, Field("")]
    engine: Annotated[str | None, Field(None)]
    voice: Annotated[str | None, Field(None)]
    emotions: Annotated[
        dict[str, TTSEmotionConfig],
        Field(default_factory=dict),
    ]

    @field_validator("engine", mode="before")
    @classmethod
    def _normalize_engine(cls, value: object) -> str | None:
        if value is None:
            return None

        normalized = str(value).strip().lower()
        if not normalized:
            return None

        allowed = {"gsv_lite", "genie_tts", "qwen_tts"}
        if normalized not in allowed:
            raise ValueError("Unsupported TTS engine. Allowed values: gsv_lite, genie_tts, qwen_tts.")

        return normalized

    @field_validator("voice", mode="before")
    @classmethod
    def _normalize_voice(cls, value: object) -> str | None:
        if value is None:
            return None

        normalized = str(value).strip()
        if not normalized:
            return None

        return normalized


class CharacterSettings(BaseModel):
    """运行时使用的角色配置。

    该模型是内部数据结构，用于承接 profile 中的 `[character]`
    配置，供 websocket、显示层与 TTS 链路复用。

    Attributes:
        profile_id: 从 profile 文件名派生的唯一标识，用于聊天历史目录。
        live2d_model_name: Live2D 模型名。
        character_name: 展示用角色名。
        avatar: 展示用头像。
        human_name: 人类一侧展示名称。
        tts_preprocessor_config: TTS 文本预处理配置。
        tts_config: 角色 TTS 配置。
    """

    profile_id: Annotated[str, Field("")]
    live2d_model_name: Annotated[str, Field("")]
    character_name: Annotated[str, Field("")]
    avatar: Annotated[str, Field("")]
    human_name: Annotated[str, Field("Human")]
    tts_preprocessor_config: Annotated[TTSPreprocessorConfig, Field(TTSPreprocessorConfig())]  # ty: ignore[missing-argument]
    tts_config: Annotated[
        TTSConfig,
        Field(
            default_factory=lambda: TTSConfig(
                character_name="",
                engine=None,
                voice=None,
                emotions={},
            )
        ),
    ]


class VtuberSettings(BaseModel):
    """兼容旧模块导入的占位配置。

    现在角色配置已经迁移到 profile 文件中，这里保留空模型，
    仅用于避免旧的导入路径失效。
    """


def scan_bg_directory() -> list[str]:
    """扫描背景图目录并返回可用文件名列表。

    Returns:
        `static/backgrounds` 下的图片文件名列表。
    """
    bg_files: list[str] = []
    bg_dir = "static/backgrounds"
    for _, _, files in os.walk(bg_dir):
        for file in files:
            if file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                bg_files.append(file)
    return bg_files
