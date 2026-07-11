from __future__ import annotations

import os
import platform
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast, overload

import tomli_w as tomlw
from pydantic import BaseModel, Field, model_validator

from lab.config_manager.abs_root import RootAbsDir
from lab.config_manager.agent import AgentSettings
from lab.config_manager.asr import ASRSettings, ASRSettingsTitle
from lab.config_manager.embedding import LocalEmbeddingSetting
from lab.config_manager.package import PackagesSettings
from lab.config_manager.server import ServerSettings

toml_dumps = tomlw.dumps
CURRENT_CONF_VERSION = "v1.6.5"

if TYPE_CHECKING:
    from lab.config_manager.qwen_asr import QwenASRSettings, QwenASRSettingsTitle
    from lab.config_manager.sherpa_asr import SherpaASRSettings, SherpaASRSettingsTitle


def xdg_config_home() -> Path:
    """返回当前平台的配置目录。

    Returns:
        平台对应的配置根目录路径。
    """
    if (env := os.environ.get("XDG_CONFIG_HOME")) and (path := Path(env)).is_absolute():
        return path

    home = Path.home()
    if platform.system() == "Windows":
        return home / "AppData"
    return home / ".config"


def search_for_settings_file(setting_name: str) -> Path | None:
    """搜索配置文件路径。

    搜索顺序为工作区 `config/`，其次是用户配置目录。

    Args:
        setting_name: 配置文件名。

    Returns:
        命中的配置文件路径；若未找到则返回 `None`。
    """
    config_dir = Path("config")
    settings_file = config_dir / setting_name
    if not settings_file.exists():
        settings_file = xdg_config_home() / setting_name
    if not settings_file.exists():
        return None
    return settings_file


@overload
def load_settings_file(setting_name: str, setting: type[SherpaASRSettings]) -> SherpaASRSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[QwenASRSettings]) -> QwenASRSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[RootAbsDir]) -> RootAbsDir: ...


@overload
def load_settings_file(setting_name: str, setting: type[AgentSettings]) -> AgentSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[PackagesSettings]) -> PackagesSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[XnneHangLabSettings]) -> XnneHangLabSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[ASRSettings]) -> ASRSettings: ...


@overload
def load_settings_file(setting_name: str, setting: type[ServerSettings]) -> ServerSettings: ...


class XnneHangLabSettings(BaseModel):
    """XnneHangLab 主配置模型。

    Attributes:
        conf_version: 配置版本号。
        asr: ASR 相关配置。
        agent: Agent 相关配置。
        local_embedding: 本地向量模型配置。
        package: 可选后端服务开关。
        root: 工作区根目录配置。
        server: 服务器配置。
    """

    conf_version: Annotated[str, Field(CURRENT_CONF_VERSION, title="配置版本")]
    asr: Annotated[ASRSettings, Field(ASRSettings())]  # ty: ignore[missing-argument]
    agent: Annotated[AgentSettings, Field(AgentSettings())]  # ty: ignore[missing-argument]
    local_embedding: Annotated[LocalEmbeddingSetting, Field(LocalEmbeddingSetting())]  # ty: ignore[missing-argument]
    package: Annotated[PackagesSettings, Field(PackagesSettings())]  # ty: ignore[missing-argument]
    root: Annotated[RootAbsDir, Field(RootAbsDir())]  # ty: ignore[missing-argument]
    server: Annotated[ServerSettings, Field(ServerSettings())]  # ty: ignore[missing-argument]

    @model_validator(mode="before")
    @classmethod
    def _normalize_conf_version(cls, value: object) -> object:
        if isinstance(value, dict):
            normalized = cast("dict[str, Any]", value)
            return {**normalized, "conf_version": CURRENT_CONF_VERSION}
        return value


def load_settings_file(
    setting_name: str,
    setting: type[
        SherpaASRSettings
        | QwenASRSettings
        | RootAbsDir
        | AgentSettings
        | PackagesSettings
        | XnneHangLabSettings
        | ASRSettings
        | ServerSettings
    ],
) -> (
    SherpaASRSettings
    | QwenASRSettings
    | RootAbsDir
    | AgentSettings
    | PackagesSettings
    | XnneHangLabSettings
    | ASRSettings
    | ServerSettings
):
    """加载并校验配置文件。

    若目标文件不存在，会先在工作区 `config/` 下创建空文件，
    再使用对应模型默认值完成补全并回写。

    Args:
        setting_name: 配置文件名。
        setting: 对应的 Pydantic 配置模型。

    Returns:
        经过校验后的配置对象。
    """
    settings_file = search_for_settings_file(setting_name=setting_name)
    if settings_file is None:
        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)
        settings_file = config_dir / setting_name
        settings_file.touch()

    with settings_file.open("r", encoding="utf-8") as file:
        settings_raw: Any = tomllib.loads(file.read())

    validated_settings = setting.model_validate(settings_raw)
    write_settings_file(settings_name=setting_name, settings=validated_settings)
    return validated_settings


def write_settings_file(
    settings_name: str,
    settings: SherpaASRSettings
    | QwenASRSettings
    | RootAbsDir
    | AgentSettings
    | PackagesSettings
    | XnneHangLabSettings
    | ASRSettings
    | ServerSettings,
) -> None:
    """将配置对象写回 TOML 文件。

    Args:
        settings_name: 配置文件名。
        settings: 已校验的配置对象。
    """
    settings_file = search_for_settings_file(setting_name=settings_name)
    if settings_file is None:
        settings_file = Path("config") / settings_name
        settings_file.touch()

    with settings_file.open("w", encoding="utf-8") as file:
        file.write(toml_dumps(settings.model_dump(exclude_none=True, by_alias=True)))


@overload
def get_setting_title(name: SherpaASRSettingsTitle, setting: type[SherpaASRSettings]) -> str: ...


@overload
def get_setting_title(name: QwenASRSettingsTitle, setting: type[QwenASRSettings]) -> str: ...


@overload
def get_setting_title(name: ASRSettingsTitle, setting: type[ASRSettings]) -> str: ...


def get_setting_title(
    name: SherpaASRSettingsTitle | QwenASRSettingsTitle | ASRSettingsTitle,
    setting: type[SherpaASRSettings | QwenASRSettings | ASRSettings],
) -> str:
    """读取配置字段的展示标题。

    Args:
        name: 字段名。
        setting: 配置模型类型。

    Returns:
        字段在 UI 中展示的标题。
    """
    return str(setting.model_fields[name].title)
