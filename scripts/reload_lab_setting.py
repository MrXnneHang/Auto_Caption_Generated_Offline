from __future__ import annotations

from lab.config_manager.agent import LLMProviderSetting
from lab.logger.logger_group import init_logger, logger

DEFAULT_PROVIDER_SEEDS: tuple[LLMProviderSetting, ...] = (
    LLMProviderSetting(
        name="deepseek",
        llm_api_key="",
        llm_base_url="https://api.deepseek.com",
        api_format="chat_completion",
    ),
    LLMProviderSetting(
        name="openai",
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        api_format="chat_completion",
    ),
    LLMProviderSetting(
        name="google",
        llm_api_key="",
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_format="chat_completion",
    ),
)


def main() -> None:
    from lab.config_manager.config import XnneHangLabSettings, write_settings_file

    init_logger()
    config_logger = logger.bind(group="config")
    settings = XnneHangLabSettings.model_validate({})
    settings.agent.llm.providers = [provider.model_copy(deep=True) for provider in DEFAULT_PROVIDER_SEEDS]
    settings.agent.chat_model.llm_provider = "deepseek"
    settings.agent.chat_model.llm_model_name = "deepseek-v4-flash-vision-exp"
    settings.agent.chat_model.support_vision = True
    settings.agent.chat_model.thinking_mode = "disabled"
    settings.agent.require_detailed = False
    write_settings_file("lab.toml", settings)
    config_logger.info(
        f"lab.toml reset successfully with seeded providers "
        f"(conf_version={settings.conf_version}, providers={len(settings.agent.llm.providers)})"
    )


if __name__ == "__main__":
    main()
