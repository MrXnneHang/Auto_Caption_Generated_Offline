from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from lab.config_manager.i18n import ASRModelProvider, Device
from lab.config_manager.qwen_asr import QwenASRSettings
from lab.config_manager.sherpa_asr import SherpaASRSettings

ASRSettingsTitle = Literal[
    "device",
    "custom_output_dir",
    "cache_dir",
    "output_dir",
    "vad_model_path",
    "asr_model_provider",
    "FFMPEG_PATH",
    "combine_line",
    "cut_line",
    "max_sentence_length",
]


class ASRSettings(BaseModel):
    FFMPEG_PATH: Annotated[str, Field("ffmpeg", title="FFMPEG path")]
    device: Annotated[Literal["cpu", "cuda"], Field("cpu", title="Device")]
    custom_output_dir: Annotated[bool, Field(False, title="Use custom output directory")]
    cache_dir: Annotated[str, Field("./cache", title="Cache directory")]
    output_dir: Annotated[str, Field("./output", title="Output directory")]
    vad_model_path: Annotated[str, Field("./models/silero_vad.onnx", title="Silero VAD model path")]
    asr_model_provider: Annotated[Literal["none", "sherpa", "qwen"], Field("sherpa", title="ASR provider")]
    punctuation_list: Annotated[str, Field("，。；、？,.;?!")]
    sherpa: Annotated[
        SherpaASRSettings,
        Field(default_factory=lambda: SherpaASRSettings()),  # ty: ignore[missing-argument]
    ]
    qwen_asr: Annotated[
        QwenASRSettings,
        Field(default_factory=lambda: QwenASRSettings()),  # ty: ignore[missing-argument]
    ]
    cut: Annotated[bool, Field(False)]
    cut_line: Annotated[int, Field(400, title="Sentence split gap (ms)")]
    combine: Annotated[bool, Field(False)]
    combine_line: Annotated[int, Field(400, title="Sentence merge gap (ms)")]
    max_sentence_length: Annotated[int, Field(20, title="Max sentence length")]

    _I18N_FIELDS = {
        "device": Device,
        "asr_model_provider": ASRModelProvider,
    }
