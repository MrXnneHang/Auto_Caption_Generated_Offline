from __future__ import annotations

from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class Packages(TypedDict):
    llm_translate: bool
    local_embedding: bool


class PackagesSettings(BaseModel):
    llm_translate: Annotated[
        bool,
        Field(False, title="LLM Translate", description="启用本地 LLM 翻译引擎"),
    ]
    local_embedding: Annotated[
        bool,
        Field(False, title="Whether to enable local GGUF embedding service"),
    ]
    sherpa_asr: Annotated[
        bool,
        Field(False, title="Sherpa ASR", description="是否安装了 sherpa-onnx ASR 引擎"),
    ]
    qwen_asr: Annotated[
        bool,
        Field(False, title="Qwen ASR", description="是否安装了 Qwen ASR 引擎"),
    ]
    gsv_lite: Annotated[
        bool,
        Field(False, title="GSV-Lite", description="是否安装了 GSV-Lite TTS 引擎"),
    ]
    genie_tts: Annotated[
        bool,
        Field(False, title="Genie TTS", description="是否安装了 Genie-TTS 引擎"),
    ]
    qwen_tts: Annotated[
        bool,
        Field(False, title="Qwen TTS", description="是否安装了 Qwen TTS 引擎"),
    ]

    def to_dict(self) -> Packages:
        return {
            "llm_translate": self.llm_translate,
            "local_embedding": self.local_embedding,
        }


def main() -> None:
    from lab.config_manager.config import (
        XnneHangLabSettings,
        load_settings_file,
        search_for_settings_file,
        write_settings_file,
    )

    package_settings_path = search_for_settings_file("package.toml")
    if package_settings_path is not None and package_settings_path.exists():
        package_settings_path.unlink()

    package_settings = load_settings_file("package.toml", PackagesSettings)
    lab_settings = load_settings_file("lab.toml", XnneHangLabSettings)
    lab_settings.package = package_settings
    write_settings_file("lab.toml", lab_settings)

    package_path = search_for_settings_file("package.toml")
    if package_path is not None and package_path.exists():
        package_path.unlink()
