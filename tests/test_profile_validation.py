from __future__ import annotations

from pathlib import Path

from lab.config_manager import XnneHangLabSettings
from lab.config_manager.validators import validate_all, validate_startup


def _base_settings(tmp_path: Path) -> XnneHangLabSettings:
    settings = XnneHangLabSettings()
    settings.root.root_dir = str(tmp_path)
    settings.agent.memory_agent_profile = ""
    settings.agent.memory_chat_profile = "profiles/congyin.toml"
    return settings


def _write_memory_chat_profile(profiles_dir: Path) -> None:
    (profiles_dir / "congyin.toml").write_text(
        """
[profile]
name = "congyin"
agent_name = "congyin"
""".strip(),
        encoding="utf-8",
    )


def test_validate_requires_memory_agent_profile() -> None:
    settings = _base_settings(Path.cwd())

    errors = validate_all(settings)

    assert any("[agent.memory_agent_profile]" in err for err in errors)
    assert any("active profile" in err for err in errors)


def test_validate_requires_character_in_memory_agent_profile(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[prompt]
persona = "prompts/characters/elaina.md"
format = "prompts/formats/emotion_bracket.md"
""".strip(),
        encoding="utf-8",
    )
    (profiles_dir / "congyin.toml").write_text(
        """
[profile]
name = "congyin"
agent_name = "congyin"
""".strip(),
        encoding="utf-8",
    )

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"

    errors = validate_all(settings)

    assert any("缺少 [character]" in err for err in errors)


def test_validate_rejects_duplicate_live2d_appearance_preset_keys(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[prompt]
persona = "prompts/characters/elaina.md"
format = "prompts/formats/emotion_bracket.md"

[plugins]
enabled = ["live2d_control"]

[[plugins.live2d_control.appearance_presets]]
key = "默认"
description = "A"

[[plugins.live2d_control.appearance_presets]]
key = "默认"
description = "B"
""".strip(),
        encoding="utf-8",
    )
    (profiles_dir / "congyin.toml").write_text(
        """
[profile]
name = "congyin"
agent_name = "congyin"
""".strip(),
        encoding="utf-8",
    )

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"

    errors = validate_all(settings)

    assert any("[plugins.live2d_control]" in err for err in errors)
    assert any("duplicate key" in err for err in errors)


def test_validate_uses_active_profile_character_tts_model(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"

[prompt]
persona = "prompts/characters/elaina.md"
format = "prompts/formats/emotion_bracket.md"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"

    errors = validate_all(settings)

    assert any("models" in err and "genie-tts" in err and "baoqiao" in err for err in errors)


def test_validate_uses_gsv_lite_engine_model_directory(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"
    settings.agent.tts.provider = "gsv_lite"
    settings.package.gsv_lite = True

    errors = validate_all(settings)

    assert any("gsv-tts-lite" in err and "baoqiao" in err for err in errors)
    assert any("GSVLiteData" in err for err in errors)


def test_validate_uses_genie_tts_engine_model_directory(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"
    settings.agent.tts.provider = "genie_tts"
    settings.package.genie_tts = True

    errors = validate_all(settings)

    assert any("genie-tts" in err and "baoqiao" in err for err in errors)


def test_validate_prefers_profile_tts_engine_over_global_provider(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
engine = "qwen_tts"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"
    settings.package.qwen_tts = False

    validate_all(settings)

    assert settings.package.qwen_tts is True


def test_validate_prefers_voice_toml_engine_over_global_provider(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
voice = "baoqiao-soft"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)
    voice_config_dir = tmp_path / "config" / "voices"
    voice_config_dir.mkdir(parents=True)
    (voice_config_dir / "baoqiao-soft.toml").write_text(
        """
[voice]
name = "baoqiao-soft"
preferred_engine = "gsv_lite"
""".strip(),
        encoding="utf-8",
    )

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"
    settings.package.gsv_lite = False

    validate_all(settings)

    assert settings.package.gsv_lite is True


def test_validate_reports_missing_explicit_voice_config(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
voice = "missing-voice"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"

    errors = validate_all(settings)

    assert any("[character.tts.voice]" in err for err in errors)
    assert any('voice = "missing-voice"' in err for err in errors)


def test_validate_skips_inactive_tts_package_model_checks_when_profile_engine_overrides(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "vtuber.toml").write_text(
        """
[profile]
name = "vtuber"
agent_name = "vtuber"

[character]
conf_name = "vtuber-local"
conf_uid = "vtuber-local-001"
live2d_model_name = "Baoqiao"
character_name = "VTuber"
avatar = "avatar.png"
human_name = "Human"

[character.tts]
character_name = "baoqiao"
engine = "qwen_tts"
""".strip(),
        encoding="utf-8",
    )
    _write_memory_chat_profile(profiles_dir)
    (tmp_path / "models" / "Qwen3-TTS-12Hz-0.6B-Base").mkdir(parents=True)

    settings = _base_settings(tmp_path)
    settings.agent.memory_agent_profile = "profiles/vtuber.toml"
    settings.package.qwen_tts = True
    settings.package.genie_tts = True

    errors = validate_all(settings)

    assert not any("Genie-TTS character model directory" in err and "baoqiao" in err for err in errors)


def test_validate_rejects_disabled_sherpa_provider_selection(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.asr.asr_model_provider = "sherpa"
    settings.package.sherpa_asr = False
    settings.package.qwen_asr = False

    errors = validate_all(settings)

    assert any('asr_model_provider = "sherpa"' in err for err in errors)
    assert any("package.sherpa_asr = false" in err for err in errors)


def test_validate_rejects_disabled_qwen_provider_selection(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.asr.asr_model_provider = "qwen"
    settings.package.sherpa_asr = False
    settings.package.qwen_asr = False

    errors = validate_all(settings)

    assert any('asr_model_provider = "qwen"' in err for err in errors)
    assert any("package.qwen_asr = false" in err for err in errors)


def test_validate_startup_warns_for_disabled_asr_provider_selection(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.asr.asr_model_provider = "sherpa"
    settings.package.sherpa_asr = False
    settings.package.qwen_asr = False

    errors, warnings = validate_startup(settings)

    assert not any('asr_model_provider = "sherpa"' in err for err in errors)
    assert any('asr_model_provider = "sherpa"' in warning for warning in warnings)


def test_validate_auto_enables_disabled_qwen_tts_package(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.agent.tts.provider = "qwen_tts"
    settings.package.qwen_tts = False

    validate_all(settings)

    assert settings.package.qwen_tts is True


def test_validate_auto_enables_disabled_gsv_lite_package(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.agent.tts.provider = "gsv_lite"
    settings.package.gsv_lite = False

    validate_all(settings)

    assert settings.package.gsv_lite is True


def test_validate_auto_enables_disabled_genie_tts_package(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path)
    settings.agent.tts.provider = "genie_tts"
    settings.package.genie_tts = False

    validate_all(settings)

    assert settings.package.genie_tts is True
