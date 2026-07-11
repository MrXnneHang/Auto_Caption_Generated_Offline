from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lab.config_manager.qwen_tts import QwenTTSSettings

LLM_Provider = str
TranslateProvider = Literal["none", "llm", "deeplx"]
TTSProvider = Literal["none", "gsv_lite", "genie_tts", "qwen_tts"]
GenieTTSLanguage = Literal["Chinese", "English", "Japanese", "Hybrid-Chinese-English", "Korean", "auto"]


class ChatModelSetting(BaseModel):
    llm_provider: Annotated[str, Field("", title="LLM Provider for Chat Model")]
    llm_model_name: Annotated[str, Field("", title="Chat Model Name")]
    support_vision: Annotated[bool, Field(False, title="Whether the chat model supports vision input")]


class VisionModelSetting(BaseModel):
    llm_provider: Annotated[str, Field("", title="LLM Provider for Vision Model")]
    llm_model_name: Annotated[str, Field("", title="Vision Model Name")]


class LLMProviderSetting(BaseModel):
    name: Annotated[str, Field(..., title="Provider Name")]
    llm_api_key: Annotated[str, Field("", title="LLM API Key")]
    llm_base_url: Annotated[str, Field("", title="LLM API Base URL")]
    api_format: Annotated[
        Literal["chat_completion"],
        Field("chat_completion", title="API Format"),
    ]

    @model_validator(mode="after")
    def validate_name(self) -> LLMProviderSetting:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("provider name cannot be empty")
        return self


class LLMSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    providers: Annotated[list[LLMProviderSetting], Field(default_factory=list)]

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        raw = cast("dict[str, Any]", value)
        if isinstance(raw.get("providers"), list):
            return raw

        providers: list[dict[str, Any]] = []
        for key, candidate in raw.items():
            if key == "providers" or not isinstance(candidate, dict):
                continue
            candidate_map = cast("dict[object, Any]", candidate)
            entry = {str(item_key): item_value for item_key, item_value in candidate_map.items()}
            entry["name"] = key.replace("_", "-")
            providers.append(entry)

        if providers:
            return {"providers": providers}

        return raw

    @model_validator(mode="after")
    def validate_providers(self) -> LLMSettings:
        seen: set[str] = set()
        normalized: list[LLMProviderSetting] = []
        for provider in self.providers:
            name = provider.name.strip()
            if name in seen:
                raise ValueError(f"duplicate provider name: {name}")
            seen.add(name)
            provider.name = name
            normalized.append(provider)
        self.providers = normalized
        return self

    def get_provider_config(self, provider: str) -> LLMProviderSetting:
        provider_name = str(provider).strip()
        for item in self.providers:
            if item.name == provider_name:
                return item
        raise KeyError(f"LLM provider not found: {provider_name}")

    def has_provider(self, provider: str) -> bool:
        provider_name = str(provider).strip()
        return any(item.name == provider_name for item in self.providers)


class PromptSettings(BaseModel):
    """Paths to agent-side prompt files."""

    vision_prompt: Annotated[
        str,
        Field("./prompts/vision_prompt.txt", title="Vision Prompt"),
    ]


class DeepLXTranslateSetting(BaseModel):
    api_key: Annotated[str, Field("", title="DeepLX API Key")]


class LLMTranslateSetting(BaseModel):
    model_path: Annotated[
        str,
        Field(
            "./models/qwen2.5-0.5b-instruct-q8_0.gguf",
            title="LLM Translate Model Path",
            description="Local GGUF model path, for example ./models/qwen2.5-0.5b-instruct-q8_0.gguf",
        ),
    ]
    n_gpu_layers: Annotated[
        int,
        Field(
            0,
            title="LLM Translate GPU Layers",
            description="GPU acceleration layer count, 0 for CPU only and -1 for full GPU",
        ),
    ]


class TranslateSettings(BaseModel):
    deeplx: Annotated[DeepLXTranslateSetting, Field(DeepLXTranslateSetting())]  # ty: ignore[missing-argument]
    llm: Annotated[LLMTranslateSetting, Field(LLMTranslateSetting())]  # ty: ignore[missing-argument]


class GSVLiteTTSSettings(BaseModel):
    use_bert: Annotated[
        bool,
        Field(
            False,
            title="Enable Chinese BERT features for GSV-Lite",
            description="Improves Chinese prosody, but may hurt non-Chinese output depending on the model and text.",
        ),
    ]


class GenieTTSSettings(BaseModel):
    language: Annotated[
        str,
        Field(
            "auto",
            title="Genie-TTS Character Language Override",
            description=(
                "Genie-TTS model language override. "
                "Defaults to auto; when left empty explicitly, XnneHangLab falls back to infer.json and then auto."
            ),
        ),
    ]
    use_roberta: Annotated[
        bool,
        Field(
            False,
            title="Enable Chinese RoBERTa features for Genie-TTS",
            description="Improves Chinese prosody when RoBERTa assets are installed, but keeps the default download unchanged.",
        ),
    ]
    onnx_intra_threads: Annotated[
        int,
        Field(
            4,
            ge=0,
            title="Genie-TTS ONNX Intra-Op Thread Count",
            description=(
                "Number of CPU threads allocated to each ONNX session (intra_op_num_threads). "
                "Set to 0 to let ONNX Runtime decide automatically. "
                "A non-zero value keeps CPU resources allocated between inferences, "
                "preventing cold-inference latency spikes."
            ),
        ),
    ]

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> str:
        if value is None:
            return "auto"

        normalized = str(value).strip()
        if not normalized:
            return "auto"

        alias_map: dict[str, GenieTTSLanguage] = {
            "chinese": "Chinese",
            "english": "English",
            "japanese": "Japanese",
            "hybrid-chinese-english": "Hybrid-Chinese-English",
            "korean": "Korean",
            "auto": "auto",
        }
        resolved = alias_map.get(normalized.lower())
        if resolved is None:
            raise ValueError(
                "Unsupported Genie-TTS language override. "
                "Allowed values: Chinese, English, Japanese, Hybrid-Chinese-English, Korean, auto."
            )
        return resolved


class TTSSettings(BaseModel):
    provider: Annotated[
        TTSProvider,
        Field(
            "genie_tts",
            title="TTS Provider",
            description="Active TTS backend.",
        ),
    ]
    voice_assets_root: Annotated[
        str,
        Field(
            "./voices",
            title="Voice Assets Root",
            description="Root directory for engine-agnostic voice assets such as emotions/*.wav and speaker/*.wav.",
        ),
    ]
    gsv_lite: Annotated[GSVLiteTTSSettings, Field(GSVLiteTTSSettings())]  # ty: ignore[missing-argument]
    genie_tts: Annotated[GenieTTSSettings, Field(GenieTTSSettings())]  # ty: ignore[missing-argument]


class AgentSettings(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_tts_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        raw = dict(cast("dict[str, Any]", value))
        raw_tts_value = raw.get("tts")
        raw_tts: dict[str, Any]
        if isinstance(raw_tts_value, dict):
            raw_tts_map = cast("dict[object, Any]", raw_tts_value)
            raw_tts = {str(key): value for key, value in raw_tts_map.items()}
        else:
            raw_tts = {}

        if "provider" not in raw_tts and isinstance(raw.get("speaker_model"), str):
            raw_tts = {**raw_tts, "provider": raw["speaker_model"]}

        if raw_tts:
            raw["tts"] = raw_tts

        return raw

    chat_model: Annotated[ChatModelSetting, Field(ChatModelSetting())]  # ty: ignore[missing-argument]
    vision_model: Annotated[VisionModelSetting, Field(VisionModelSetting())]  # ty: ignore[missing-argument]
    enable_tool: Annotated[bool, Field(True, title="Enable Tool Calling (BuiltinTool)")]
    prompts: Annotated[PromptSettings, Field(PromptSettings())]  # ty: ignore[missing-argument]
    llm: Annotated[LLMSettings, Field(LLMSettings())]  # ty: ignore[missing-argument]
    translate_provider: Annotated[TranslateProvider, Field("none", title="Translation Provider")]
    translate: Annotated[TranslateSettings, Field(TranslateSettings())]  # ty: ignore[missing-argument]
    user_lang: Annotated[Literal["ZH", "EN", "JA"], Field("ZH", title="User Language")]
    speaker_lang: Annotated[Literal["ZH", "EN", "JA"], Field("ZH", title="Speaker Language")]
    tts: Annotated[TTSSettings, Field(TTSSettings())]  # ty: ignore[missing-argument]
    qwen_tts: Annotated[QwenTTSSettings, Field(QwenTTSSettings())]  # ty: ignore[missing-argument]
    faster_first_response: Annotated[bool, Field(False, title="Faster First Response")]
    max_vision_concurrency: Annotated[
        int,
        Field(
            default=4,
            ge=1,
            title="Maximum concurrent vision requests",
        ),
    ]
    require_detailed: Annotated[bool, Field(True, title="Require Detailed Vision Summary")]
    structured_history_full_turns: Annotated[
        int,
        Field(
            default=5,
            ge=0,
            title="Recent conversation turns that keep full structured history",
            description="鎸夊璇濊疆鏁拌锛屾渶杩戜繚鐣欏畬鏁寸粨鏋勫寲 user history 鐨勮疆鏁帮紱鏇存棭杞灏嗗洖閫€涓?brief 鎽樿銆?",
        ),
    ]
    segment_method: Literal["regex", "pysbd"] = Field(
        "pysbd",
        title="Segment Method",
        description="Method for segmenting text. 'regex' uses regex, 'pysbd' uses pysbd.",
    )
    interrupt_method: Literal["system", "user"] = Field(
        "user",
        title="Interrupt Method",
        description="Method for writing interruptions signal in chat history. 'system' uses system prompt, 'user' uses user input.",
    )
    memory_agent_profile: Annotated[
        str,
        Field("profiles/baoqiao.toml", title="Profile path for MemoryAgent"),
    ]
    memory_chat_profile: Annotated[
        str,
        Field("profiles/congyin.toml", title="Profile path for /memory/chat"),
    ]

    @model_validator(mode="after")
    def validate_model_providers(self) -> AgentSettings:
        for field_name, provider_name in (
            ("chat_model", self.chat_model.llm_provider),
            ("vision_model", self.vision_model.llm_provider),
        ):
            normalized = provider_name.strip()
            if normalized and not self.llm.has_provider(normalized):
                raise ValueError(f"Unknown LLM provider reference: {field_name}.llm_provider={provider_name}")
        return self

    @property
    def speaker_model(self) -> TTSProvider:
        return self.tts.provider

    @speaker_model.setter
    def speaker_model(self, value: TTSProvider) -> None:
        self.tts.provider = value


def main() -> None:
    from lab.config_manager.config import (
        XnneHangLabSettings,
        load_settings_file,
        search_for_settings_file,
        write_settings_file,
    )

    agent_settings_path = search_for_settings_file("agent.toml")
    if agent_settings_path is not None and agent_settings_path.exists():
        agent_settings_path.unlink()
    agent_settings = load_settings_file("agent.toml", AgentSettings)
    lab_settings = load_settings_file("lab.toml", XnneHangLabSettings)
    lab_settings.agent = agent_settings
    write_settings_file("lab.toml", lab_settings)
    agent_path = search_for_settings_file("agent.toml")
    if agent_path is not None and agent_path.exists():
        agent_path.unlink()


if __name__ == "__main__":
    main()
