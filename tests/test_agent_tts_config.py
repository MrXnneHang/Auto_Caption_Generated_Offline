from __future__ import annotations

from lab.config_manager.agent import AgentSettings


def test_agent_settings_migrate_legacy_speaker_model() -> None:
    settings = AgentSettings.model_validate({"speaker_model": "qwen_tts"})

    assert settings.tts.provider == "qwen_tts"
    assert settings.speaker_model == "qwen_tts"
    assert "speaker_model" not in settings.model_dump()


def test_agent_settings_defaults_to_disabled_tts() -> None:
    settings = AgentSettings.model_validate({})

    assert settings.tts.provider == "none"


def test_agent_settings_gsv_lite_use_bert_defaults_to_false() -> None:
    settings = AgentSettings.model_validate({"tts": {"provider": "gsv_lite"}})

    assert settings.tts.provider == "gsv_lite"
    assert settings.tts.gsv_lite.use_bert is False


def test_agent_settings_gsv_lite_use_bert_can_be_enabled() -> None:
    settings = AgentSettings.model_validate(
        {
            "tts": {
                "provider": "gsv_lite",
                "gsv_lite": {
                    "use_bert": True,
                },
            }
        }
    )

    assert settings.tts.provider == "gsv_lite"
    assert settings.tts.gsv_lite.use_bert is True


def test_agent_settings_genie_tts_use_roberta_defaults_to_false() -> None:
    settings = AgentSettings.model_validate({"tts": {"provider": "genie_tts"}})

    assert settings.tts.provider == "genie_tts"
    assert settings.tts.genie_tts.use_roberta is False


def test_agent_settings_genie_tts_use_roberta_can_be_enabled() -> None:
    settings = AgentSettings.model_validate(
        {
            "tts": {
                "provider": "genie_tts",
                "genie_tts": {
                    "use_roberta": True,
                },
            }
        }
    )

    assert settings.tts.provider == "genie_tts"
    assert settings.tts.genie_tts.use_roberta is True


def test_profile_tts_engine_accepts_known_engine_names() -> None:
    from lab.profile.schema import TTSConfig

    config = TTSConfig.model_validate({"character_name": "baoqiao", "engine": "QWEN_TTS"})

    assert config.engine == "qwen_tts"
