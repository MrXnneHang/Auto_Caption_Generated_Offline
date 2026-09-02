"""声明式配置校验框架。

每个 package 通过 `PackageRule` 声明自己的模型依赖和 package
间依赖。校验引擎只校验已启用的 package，并为每个错误提供具体的修复提示。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic import ValidationError

from lab.plugin.config import validate_plugin_override

if TYPE_CHECKING:
    from collections.abc import Callable

    from lab.config_manager.config import XnneHangLabSettings


def _default_depends_on() -> list[str]:
    """返回默认的 package 依赖列表。

    Returns:
        空的依赖列表。
    """
    return []


def _default_models() -> list[ModelRequirement]:
    """返回默认的模型依赖列表。

    Returns:
        空的模型依赖列表。
    """
    return []


def _default_extra_checks() -> list[Callable[[XnneHangLabSettings], str | None]]:
    """返回默认的额外校验函数列表。

    Returns:
        空的额外校验列表。
    """
    return []


@dataclass
class ModelRequirement:
    """描述单个模型文件或目录的校验规则。

    Attributes:
        name: 显示名，用于拼接错误信息。
        path_getter: 从完整配置中提取模型路径的函数。
        install_hint: 对应的安装提示命令。
        is_dir: 是否要求目标路径为目录。
    """

    name: str
    path_getter: Callable[[XnneHangLabSettings], Path | None]
    install_hint: str
    is_dir: bool = False


@dataclass
class PackageRule:
    """描述单个 package 的完整校验规则。

    Attributes:
        package_name: 对应 `PackagesSettings` 中的字段名。
        depends_on: 依赖的其他 package 名称列表。
        models: 需要存在的模型文件或目录列表。
        extra_checks: 额外校验函数列表。
    """

    package_name: str
    depends_on: list[str] = field(default_factory=_default_depends_on)
    models: list[ModelRequirement] = field(default_factory=_default_models)
    extra_checks: list[Callable[[XnneHangLabSettings], str | None]] = field(default_factory=_default_extra_checks)


def _resolve_path(settings: XnneHangLabSettings, raw_path: str) -> Path | None:
    """将配置中的路径解析为绝对路径。

    Args:
        settings: 完整配置对象。
        raw_path: 配置中的原始路径字符串。

    Returns:
        解析后的绝对路径；若路径为空则返回 `None`。
    """
    if not raw_path or not raw_path.strip():
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(settings.root.root_dir) / path
    return path


def _resolve_active_character_name(settings: XnneHangLabSettings) -> str | None:
    """Resolve the active character name from the current profile."""
    profile_path = _resolve_path(settings, settings.agent.memory_agent_profile)
    if profile_path is None or not profile_path.exists():
        return None

    try:
        with profile_path.open("rb") as file:
            profile_data: dict[str, object] = tomllib.load(file)
    except Exception:
        return None

    character_obj = profile_data.get("character")
    if not isinstance(character_obj, dict):
        return None
    character_data = cast("dict[str, object]", character_obj)

    tts_obj = character_data.get("tts")
    if isinstance(tts_obj, dict):
        tts_data = cast("dict[str, object]", tts_obj)
        tts_character_name = tts_data.get("character_name")
        if isinstance(tts_character_name, str) and tts_character_name.strip():
            return tts_character_name.strip()

    character_name = character_data.get("character_name")
    if isinstance(character_name, str) and character_name.strip():
        return character_name.strip()

    return None


def _normalize_optional_tts_provider(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    if normalized not in {"gsv_lite", "genie_tts", "qwen_tts"}:
        return None

    return normalized


def _resolve_active_voice_id(settings: XnneHangLabSettings) -> str | None:
    profile_path = _resolve_path(settings, settings.agent.memory_agent_profile)
    if profile_path is None or not profile_path.exists():
        return None

    try:
        with profile_path.open("rb") as file:
            profile_data: dict[str, object] = tomllib.load(file)
    except Exception:
        return None

    character_obj = profile_data.get("character")
    if not isinstance(character_obj, dict):
        return None
    character_data = cast("dict[str, object]", character_obj)

    tts_obj = character_data.get("tts")
    if isinstance(tts_obj, dict):
        tts_data = cast("dict[str, object]", tts_obj)
        voice_id = tts_data.get("voice")
        if isinstance(voice_id, str) and voice_id.strip():
            return voice_id.strip()

    return None


def _check_profile_voice_config(
    *,
    ws_root: Path,
    profile_label: str,
    character_obj: dict[str, object],
) -> str | None:
    tts_obj = character_obj.get("tts")
    if not isinstance(tts_obj, dict):
        return None

    tts_data = cast("dict[str, object]", tts_obj)
    raw_voice = tts_data.get("voice")
    if not isinstance(raw_voice, str) or not raw_voice.strip():
        return None

    voice_id = raw_voice.strip()
    voice_toml_path = ws_root / "config" / "voices" / f"{voice_id}.toml"
    if voice_toml_path.is_file():
        return None

    return (
        f" [character.tts.voice]\n"
        f" profile '{profile_label}' 指定了 voice = \"{voice_id}\"，但配置文件不存在: {voice_toml_path}\n"
        f" -> 创建 config/voices/{voice_id}.toml，或删除 profile 里的 voice 字段"
    )


def _resolve_active_profile_tts_engine(settings: XnneHangLabSettings) -> str | None:
    profile_path = _resolve_path(settings, settings.agent.memory_agent_profile)
    if profile_path is None or not profile_path.exists():
        return None

    try:
        with profile_path.open("rb") as file:
            profile_data: dict[str, object] = tomllib.load(file)
    except Exception:
        return None

    character_obj = profile_data.get("character")
    if not isinstance(character_obj, dict):
        return None
    character_data = cast("dict[str, object]", character_obj)

    tts_obj = character_data.get("tts")
    if not isinstance(tts_obj, dict):
        return None
    tts_data = cast("dict[str, object]", tts_obj)

    return _normalize_optional_tts_provider(tts_data.get("engine"))


def _resolve_voice_preferred_engine(settings: XnneHangLabSettings, voice_id: str | None) -> str | None:
    if voice_id is None or not voice_id.strip():
        return None

    voice_toml_path = Path(settings.root.root_dir) / "config" / "voices" / f"{voice_id.strip()}.toml"
    if not voice_toml_path.exists():
        return None

    try:
        with voice_toml_path.open("rb") as file:
            voice_data: dict[str, object] = tomllib.load(file)
    except Exception:
        return None

    voice_obj = voice_data.get("voice")
    if not isinstance(voice_obj, dict):
        return None

    voice_section = cast("dict[str, object]", voice_obj)
    return _normalize_optional_tts_provider(voice_section.get("preferred_engine"))


def _resolve_active_tts_provider(settings: XnneHangLabSettings) -> str:
    profile_engine = _resolve_active_profile_tts_engine(settings)
    if profile_engine is not None:
        return profile_engine

    voice_engine = _resolve_voice_preferred_engine(settings, _resolve_active_voice_id(settings))
    if voice_engine is not None:
        return voice_engine

    return settings.agent.tts.provider


def _resolve_preferred_character_model_path(
    settings: XnneHangLabSettings,
    *,
    preferred_dirname: str,
    fallback_dirname: str | None = None,
) -> Path | None:
    character_name = _resolve_active_character_name(settings)
    if character_name is None:
        return None

    models_dir = Path(settings.root.root_dir) / "models"
    preferred = models_dir / preferred_dirname / character_name
    if preferred.exists():
        return preferred

    if fallback_dirname is not None:
        fallback = models_dir / fallback_dirname / character_name
        if fallback.exists():
            return fallback

    return preferred


def _resolve_active_gsv_lite_model_path(settings: XnneHangLabSettings) -> Path | None:
    return _resolve_preferred_character_model_path(
        settings,
        preferred_dirname="gsv-tts-lite",
    )


def _resolve_active_genie_tts_model_path(settings: XnneHangLabSettings) -> Path | None:
    return _resolve_preferred_character_model_path(
        settings,
        preferred_dirname="genie-tts",
    )


def _resolve_gsv_lite_data_root(settings: XnneHangLabSettings) -> Path:
    models_root = Path(settings.root.root_dir) / "models"
    preferred = models_root / "GSVLiteData"
    if preferred.exists():
        return preferred

    legacy_paths = (
        models_root / "chinese-hubert-base",
        models_root / "g2p",
        models_root / "sv",
        models_root / "chinese-roberta-wwm-ext-large",
    )
    if any(path.exists() for path in legacy_paths):
        return models_root

    return preferred


def _resolve_gsv_lite_resource_path(settings: XnneHangLabSettings, *parts: str) -> Path:
    return _resolve_gsv_lite_data_root(settings).joinpath(*parts)


def _resolve_active_qwen_tts_model_path(settings: XnneHangLabSettings) -> Path | None:
    model_name = settings.agent.qwen_tts.model_name
    if model_name == "0.6b":
        return _resolve_path(settings, settings.agent.qwen_tts.model_0_6b_path)
    return _resolve_path(settings, settings.agent.qwen_tts.model_1_7b_path)


def _check_gsv_lite_roberta_when_enabled(settings: XnneHangLabSettings) -> str | None:
    if settings.agent.tts.provider != "gsv_lite":
        return None
    if not settings.agent.tts.gsv_lite.use_bert:
        return None

    roberta_dir = _resolve_gsv_lite_resource_path(settings, "chinese-roberta-wwm-ext-large")
    if roberta_dir.is_dir():
        return None

    return (
        " [gsv_lite]\n"
        f" GSV-Lite Chinese RoBERTa resource does not exist: {roberta_dir}\n"
        " -> Run `just install-gsv-lite-data`"
    )


def _check_qwen_asr_preload_models(settings: XnneHangLabSettings) -> str | None:
    """校验 `qwen_asr.preload_models` 中声明的模型路径。

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息；若校验通过则返回 `None`。
    """
    missing: list[str] = []
    for model_name in settings.asr.qwen_asr.preload_models:
        if model_name == "0.6b":
            path = _resolve_path(settings, settings.asr.qwen_asr.model_0_6b_path)
        elif model_name == "1.7b":
            path = _resolve_path(settings, settings.asr.qwen_asr.model_1_7b_path)
        else:
            continue

        if path is not None and not path.exists():
            missing.append(f" preload model '{model_name}' 不存在: {path}")

    if missing:
        return (
            " [asr.qwen_asr]\n"
            " preload_models 中指定的模型不存在:\n" + "\n".join(missing) + "\n"
            " -> 运行 `just install-qwen-asr`"
        )
    return None


def _check_chat_api_key(settings: XnneHangLabSettings) -> str | None:
    """校验当前聊天模型 provider 的 API key。

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息；若校验通过则返回 `None`。
    """
    chat_provider = settings.agent.chat_model.llm_provider
    try:
        llm_cfg = settings.agent.llm.get_provider_config(chat_provider)
    except KeyError:
        return (
            " [agent.llm.providers]\n"
            f" 当前 chat_model 引用了不存在的 provider: {chat_provider}\n"
            " -> 检查 [agent.chat_model].llm_provider，或在 [[agent.llm.providers]] 中补齐同名 provider"
        )
    if not llm_cfg.llm_api_key:
        return (
            " [agent.llm.providers]\n"
            " llm_api_key 未配置\n"
            f' -> 在 [[agent.llm.providers]] 中找到 name = "{chat_provider}" 的条目并设置 llm_api_key'
        )
    return None


def _check_translate_config(settings: XnneHangLabSettings) -> str | None:
    """校验翻译 provider 与其配置是否一致。

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息；若校验通过则返回 `None`。
    """
    translate_provider = settings.agent.translate_provider
    if translate_provider == "none":
        return None
    if translate_provider == "deeplx" and not settings.agent.translate.deeplx.api_key.strip():
        return (
            " [agent.translate.deeplx]\n"
            " 当前翻译 provider 为 deeplx，但 api_key 为空\n"
            ' -> 配置 [agent.translate.deeplx].api_key，或将 [agent].translate_provider 改为 "llm"'
        )

    if translate_provider == "llm" and not settings.package.llm_translate:
        return (
            " [package]\n"
            " 当前翻译 provider 为 llm，但 package.llm_translate = false\n"
            " -> 在 [package] 下设置 llm_translate = true，并运行 `just install-llm-translate`\n"
            ' 或将 [agent].translate_provider 改为 "deeplx" 并配置 key'
        )

    return None


def _check_profiles(settings: XnneHangLabSettings) -> list[str]:
    """校验 profile 路径及其角色字段。

    `memory_agent_profile` 现在不再回退到 `lab.toml`，
    因此激活的 VTuber profile 必须存在且必须声明 `[character]`。

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息列表。
    """
    errors: list[str] = []
    ws_root = Path(settings.root.root_dir)

    memory_agent_profile = settings.agent.memory_agent_profile
    if not memory_agent_profile:
        errors.append(
            " [agent.memory_agent_profile]\n"
            " VTuber 主链路未配置 active profile\n"
            ' -> 在 [agent] 下设置 memory_agent_profile = "profiles/xxx.toml"'
        )
    else:
        profile_path = Path(memory_agent_profile)
        if not profile_path.is_absolute():
            profile_path = ws_root / memory_agent_profile

        if not profile_path.exists():
            errors.append(
                f" [agent.memory_agent_profile]\n"
                f" 文件不存在: {profile_path}\n"
                " -> 检查路径是否正确，或创建对应的 profile 文件"
            )
        else:
            try:
                with profile_path.open("rb") as file:
                    profile_data: dict[str, object] = tomllib.load(file)
            except Exception as exc:
                errors.append(f" [agent.memory_agent_profile]\n profile 解析失败: {profile_path}\n -> {exc}")
            else:
                character_obj = profile_data.get("character")
                if not isinstance(character_obj, dict):
                    errors.append(
                        " [agent.memory_agent_profile]\n"
                        f" profile '{memory_agent_profile}' 缺少 [character] 配置\n"
                        " -> VTuber 主链路的 active profile 必须在 profile 中声明 [character]"
                    )
                else:
                    voice_config_err = _check_profile_voice_config(
                        ws_root=ws_root,
                        profile_label=memory_agent_profile,
                        character_obj=cast("dict[str, object]", character_obj),
                    )
                    if voice_config_err:
                        errors.append(voice_config_err)

                plugins_obj = profile_data.get("plugins")
                if isinstance(plugins_obj, dict):
                    plugins_dict = cast("dict[str, object]", plugins_obj)
                    errors += _check_profile_plugin_overrides(
                        ws_root=ws_root,
                        profile_label=memory_agent_profile,
                        plugins_obj=plugins_dict,
                    )

    memory_chat_profile = settings.agent.memory_chat_profile
    if memory_chat_profile:
        chat_profile_path = Path(memory_chat_profile)
        if not chat_profile_path.is_absolute():
            chat_profile_path = ws_root / memory_chat_profile
        if not chat_profile_path.exists():
            errors.append(
                f" [agent.memory_chat_profile]\n"
                f" 文件不存在: {chat_profile_path}\n"
                " -> 检查路径是否正确，或创建对应的 profile 文件"
            )
        else:
            try:
                with chat_profile_path.open("rb") as file:
                    chat_profile_data: dict[str, object] = tomllib.load(file)
            except Exception as exc:
                errors.append(f" [agent.memory_chat_profile]\n profile 解析失败: {chat_profile_path}\n -> {exc}")
            else:
                plugins_obj = chat_profile_data.get("plugins")
                if isinstance(plugins_obj, dict):
                    errors += _check_profile_plugin_overrides(
                        ws_root=ws_root,
                        profile_label=memory_chat_profile,
                        plugins_obj=cast("dict[str, object]", plugins_obj),
                    )

    return errors


def _check_profile_plugin_overrides(
    *,
    ws_root: Path,
    profile_label: str,
    plugins_obj: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    enabled_plugins_obj = plugins_obj.get("enabled")
    enabled_plugins: list[str] = []
    if isinstance(enabled_plugins_obj, list):
        for plugin in cast("list[object]", enabled_plugins_obj):
            if isinstance(plugin, str):
                enabled_plugins.append(plugin)

    candidate_plugin_dirs = [ws_root / "src" / "lab" / "plugins", Path(__file__).resolve().parents[1] / "plugins"]
    for plugin_id in enabled_plugins:
        plugin_override = plugins_obj.get(plugin_id, {})
        if not isinstance(plugin_override, dict):
            errors.append(f" [plugins.{plugin_id}]\n profile '{profile_label}' 的插件 override 必须是 table/object")
            continue

        plugin_dir = next(
            (
                candidate_dir / plugin_id
                for candidate_dir in candidate_plugin_dirs
                if (candidate_dir / plugin_id / "plugin.toml").is_file()
            ),
            None,
        )
        if plugin_dir is None:
            continue

        try:
            validate_plugin_override(plugin_id, plugin_dir, cast("dict[str, Any]", plugin_override))
        except ValidationError as exc:
            errors.append(f" [plugins.{plugin_id}]\n profile '{profile_label}' 的插件配置无效\n -> {exc}")

    return errors


PACKAGE_RULES: list[PackageRule] = [
    PackageRule(
        package_name="local_embedding",
        models=[
            ModelRequirement(
                name="Embedding GGUF 模型 (bge-m3)",
                path_getter=lambda s: _resolve_path(s, s.local_embedding.model_path),
                install_hint="just download-local-embedding",
            ),
        ],
    ),
    PackageRule(
        package_name="llm_translate",
        models=[
            ModelRequirement(
                name="LLM Translate GGUF 模型 (Qwen2.5-0.5B)",
                path_getter=lambda s: _resolve_path(s, s.agent.translate.llm.model_path),
                install_hint="just install-llm-translate",
            ),
        ],
    ),
    PackageRule(
        package_name="sherpa_asr",
        models=[
            ModelRequirement(
                name="Sherpa-ONNX Paraformer 模型目录",
                path_getter=lambda s: _resolve_path(s, s.asr.sherpa.asr_model_dir),
                install_hint="just install-sherpa-model",
                is_dir=True,
            ),
            ModelRequirement(
                name="Silero VAD 模型",
                path_getter=lambda s: _resolve_path(s, s.asr.vad_model_path),
                install_hint="just install-sherpa-model",
            ),
        ],
    ),
    PackageRule(
        package_name="qwen_asr",
        models=[
            ModelRequirement(
                name="Qwen3-ForcedAligner 模型",
                path_getter=lambda s: (
                    _resolve_path(s, s.asr.qwen_asr.forced_aligner_path) if s.asr.qwen_asr.forced_aligner_path else None
                ),
                install_hint="just install-qwen-asr",
                is_dir=True,
            ),
        ],
        extra_checks=[_check_qwen_asr_preload_models],
    ),
    PackageRule(
        package_name="gsv_lite",
        models=[
            ModelRequirement(
                name="GSV-Lite character model directory",
                path_getter=_resolve_active_gsv_lite_model_path,
                install_hint="just install-gsv-model",
                is_dir=True,
            ),
            ModelRequirement(
                name="GSV-Lite Chinese HuBERT resource directory",
                path_getter=lambda s: _resolve_gsv_lite_resource_path(s, "chinese-hubert-base"),
                install_hint="just install-gsv-lite-data",
                is_dir=True,
            ),
            ModelRequirement(
                name="GSV-Lite G2P resource directory",
                path_getter=lambda s: _resolve_gsv_lite_resource_path(s, "g2p"),
                install_hint="just install-gsv-lite-data",
                is_dir=True,
            ),
            ModelRequirement(
                name="GSV-Lite speaker verification resource directory",
                path_getter=lambda s: _resolve_gsv_lite_resource_path(s, "sv"),
                install_hint="just install-gsv-lite-data",
                is_dir=True,
            ),
        ],
        extra_checks=[_check_gsv_lite_roberta_when_enabled],
    ),
    PackageRule(
        package_name="genie_tts",
        models=[
            ModelRequirement(
                name="Genie-TTS character model directory",
                path_getter=_resolve_active_genie_tts_model_path,
                install_hint="place exported Genie-TTS files under models/genie-tts/<character>",
                is_dir=True,
            ),
        ],
    ),
    PackageRule(
        package_name="qwen_tts",
        models=[
            ModelRequirement(
                name="Qwen3-TTS 模型 (Qwen3-TTS-12Hz-1.7B-Base)",
                path_getter=_resolve_active_qwen_tts_model_path,
                install_hint="just install-qwen-tts",
                is_dir=True,
            ),
        ],
    ),
]


def _check_provider_package_compatibility(settings: XnneHangLabSettings) -> list[str]:
    """检查已选择的 provider 是否与 package 安装状态一致。"""
    issues: list[str] = []

    active_tts = _resolve_active_tts_provider(settings)
    if active_tts in {"gsv_lite", "genie_tts", "qwen_tts"} and not getattr(settings.package, active_tts, False):
        issues.append(
            " [package]\n"
            f' tts.provider = "{active_tts}", 但 package.{active_tts} = false\n'
            f" -> 在 [package] 下设置 {active_tts} = true"
        )

    active_asr = settings.asr.asr_model_provider
    if active_asr == "sherpa" and not settings.package.sherpa_asr:
        issues.append(
            " [package]\n"
            ' asr_model_provider = "sherpa", 但 package.sherpa_asr = false\n'
            " -> 在 [package] 下设置 sherpa_asr = true"
        )
    elif active_asr == "qwen" and not settings.package.qwen_asr:
        issues.append(
            " [package]\n"
            ' asr_model_provider = "qwen", 但 package.qwen_asr = false\n'
            " -> 在 [package] 下设置 qwen_asr = true"
        )

    return issues


def validate_packages(settings: XnneHangLabSettings) -> list[str]:
    """校验已启用 package 的依赖与模型文件。

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息列表；空列表表示全部通过。
    """
    errors: list[str] = []
    active_tts_provider = _resolve_active_tts_provider(settings)
    active_asr_provider = settings.asr.asr_model_provider

    for rule in PACKAGE_RULES:
        if rule.package_name in {"gsv_lite", "genie_tts", "qwen_tts"}:
            enabled = rule.package_name == active_tts_provider and getattr(settings.package, rule.package_name, False)
        elif rule.package_name == "sherpa_asr":
            enabled = active_asr_provider == "sherpa" and settings.package.sherpa_asr
        elif rule.package_name == "qwen_asr":
            enabled = active_asr_provider == "qwen" and settings.package.qwen_asr
        else:
            enabled = getattr(settings.package, rule.package_name, False)
        if not enabled:
            continue

        for dep in rule.depends_on:
            if not getattr(settings.package, dep, False):
                errors.append(
                    f" [package]\n"
                    f" {rule.package_name} = true，但依赖的 {dep} = false\n"
                    f" -> 在 [package] 下设置 {dep} = true"
                )

        for model in rule.models:
            path = model.path_getter(settings)
            if path is None:
                errors.append(f" [{rule.package_name}]\n {model.name} 路径未配置\n -> 运行 `{model.install_hint}`")
                continue

            path_exists = path.is_dir() if model.is_dir else path.is_file()
            if not path_exists:
                errors.append(f" [{rule.package_name}]\n {model.name} 不存在: {path}\n -> 运行 `{model.install_hint}`")

        for check in rule.extra_checks:
            err = check(settings)
            if err:
                errors.append(err)

    return errors


def validate_all(settings: XnneHangLabSettings) -> list[str]:
    """执行完整配置校验。

    当前会依次校验：
    1. 聊天模型 API key
    2. 翻译配置
    3. profile 存在性与角色字段
    4. 已启用 package 的模型依赖

    Args:
        settings: 完整配置对象。

    Returns:
        错误信息列表；空列表表示全部通过。
    """
    logger.debug("Running declarative configuration validation")
    errors, _ = _collect_validation_issues(settings)
    errors += _check_provider_package_compatibility(settings)
    return errors


def validate_startup(settings: XnneHangLabSettings) -> tuple[list[str], list[str]]:
    """执行启动阶段配置校验。

    Args:
        settings: 完整配置对象。

    Returns:
        tuple[list[str], list[str]]: `(errors, warnings)`。
    """
    logger.debug("Running startup configuration validation")
    return _collect_validation_issues(settings)


def _collect_validation_issues(
    settings: XnneHangLabSettings,
) -> tuple[list[str], list[str]]:
    """汇总配置校验中的错误与警告。"""
    errors: list[str] = []
    warnings: list[str] = []

    api_err = _check_chat_api_key(settings)
    if api_err:
        errors.append(api_err)

    translate_err = _check_translate_config(settings)
    if translate_err:
        errors.append(translate_err)

    errors += _check_profiles(settings)
    errors += validate_packages(settings)
    warnings += _check_provider_package_compatibility(settings)

    return errors, warnings
