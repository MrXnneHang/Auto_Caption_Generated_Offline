from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger

from lab.agent.agent_factory import AgentFactory
from lab.api.logic.translate import TranslateEngineRouter
from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.config_manager.vtuber import (
    CharacterSettings,
    TTSConfig as VTuberTTSConfig,
    TTSEmotionConfig as VTuberTTSEmotionConfig,
    TTSPreprocessorConfig as VTuberTTSPreprocessorConfig,
)
from lab.live2d_model import Live2dModel
from lab.profile.schema import Profile

if TYPE_CHECKING:
    from fastapi import WebSocket

    from lab.agent.agents.agent_interface import AgentInterface
    from lab.config_manager.server import ServerSettings
    from lab.conversations.types import WebSocketSend


class ServiceContext:
    """保存单个会话的运行时服务实例。

    该对象负责管理当前连接所需的配置、Agent、Live2D 和翻译引擎，
    并支持根据 `lab.toml` 重新加载运行时状态。
    """

    def __init__(self, lab_setting: XnneHangLabSettings):
        """初始化默认服务上下文。"""
        self._mcp_connected = False
        self._mcp_lock = asyncio.Lock()
        self.lab_setting = lab_setting
        self.server_config: ServerSettings | None = None
        self.character_config: CharacterSettings | None = None

        self.live2d_model: Live2dModel | None = None
        self.agent_engine: AgentInterface | None = None
        self.translate_engine: TranslateEngineRouter | None = None

        self.chat_system_prompt: str | None = None
        self.vision_system_prompt: str | None = None
        self.history_uid: str = ""
        self.live2d_startup_expression_applied: bool = False

    def __str__(self) -> str:
        """返回当前上下文的可读摘要。

        Returns:
            便于日志输出的字符串表示。
        """
        return (
            f"ServiceContext:\n"
            f"  Server Config: {'Loaded' if self.server_config else 'Not Loaded'}\n"
            f"    Details: {json.dumps(self.server_config.model_dump(), indent=6) if self.server_config else 'None'}\n"
            f"  Live2D Model: {self.live2d_model.model_info if self.live2d_model else 'Not Loaded'}\n"
            f"  Chat System Prompt: {self.chat_system_prompt or 'Not Set'}\n"
            f"  Vision System Prompt: {self.vision_system_prompt or 'Not Set'}"
        )

    def load_cache(
        self,
        lab_setting: XnneHangLabSettings,
        server_config: ServerSettings | None,
        character_config: CharacterSettings | None,
        live2d_model: Live2dModel | None,
        agent_engine: AgentInterface,
    ) -> None:
        """复用已初始化的服务对象。

        Args:
            lab_setting: 当前实验室配置。
            server_config: 服务端配置。
            character_config: 当前角色运行时配置。
            live2d_model: 已初始化的 Live2D 模型。
            agent_engine: 已初始化的 Agent 引擎。

        Raises:
            ValueError: 当 `server_config` 为空时抛出。
        """
        if server_config is None:
            raise ValueError("server_config cannot be None")

        self.lab_setting = lab_setting
        self.server_config = server_config
        self.character_config = character_config
        self.live2d_model = live2d_model
        self.agent_engine = agent_engine
        self.live2d_startup_expression_applied = False
        self.init_translate(lab_setting)
        logger.debug("Loaded service context with cache: {}", character_config)

    def _resolve_profile_path(self, config: XnneHangLabSettings, profile_path_str: str) -> Path:
        """解析 profile 文件路径。

        Args:
            config: 完整配置对象。
            profile_path_str: 配置中的 profile 路径。

        Returns:
            基于 `root_dir` 解析后的绝对路径或工作区路径。
        """
        profile_path = Path(profile_path_str)
        if not profile_path.is_absolute():
            profile_path = Path(config.root.root_dir) / profile_path
        return profile_path

    def _load_active_profile(self, config: XnneHangLabSettings) -> Profile | None:
        """加载当前激活的 VTuber profile。

        Args:
            config: 完整配置对象。

        Returns:
            解析成功的 `Profile`；若未配置或加载失败则返回 `None`。
        """
        profile_path_str = config.agent.memory_agent_profile
        if not profile_path_str:
            return None

        profile_path = self._resolve_profile_path(config, profile_path_str)
        if not profile_path.exists():
            logger.warning("Active memory_agent_profile not found: {}", profile_path)
            return None

        try:
            return Profile.from_toml(profile_path)
        except Exception as exc:
            logger.warning("Failed to load profile {}: {}", profile_path, exc)
            return None

    @staticmethod
    def _to_character_settings(profile: Profile | None, profile_id: str = "") -> CharacterSettings | None:
        """将 profile 中的 `[character]` 转成内部运行时结构。

        Args:
            profile: 已加载的 profile。
            profile_id: 从 profile 文件名派生的标识符。

        Returns:
            内部 `CharacterSettings`；若 profile 未定义 `[character]` 则返回 `None`。
        """
        if profile is None or profile.character is None:
            return None

        char = profile.character
        return CharacterSettings(
            profile_id=profile_id,
            live2d_model_name=char.live2d_model_name or "",
            character_name=char.character_name,
            avatar=char.avatar,
            human_name=char.human_name,
            tts_preprocessor_config=VTuberTTSPreprocessorConfig(
                remove_special_char=char.tts_preprocessor.remove_special_char,
                ignore_brackets=char.tts_preprocessor.ignore_brackets,
                ignore_parentheses=char.tts_preprocessor.ignore_parentheses,
                ignore_asterisks=char.tts_preprocessor.ignore_asterisks,
                ignore_angle_brackets=char.tts_preprocessor.ignore_angle_brackets,
                ignore_urls=char.tts_preprocessor.ignore_urls,
            ),
            tts_config=VTuberTTSConfig(
                character_name=char.tts.character_name,
                engine=char.tts.engine,
                voice=char.tts.voice,
                emotions={
                    name: VTuberTTSEmotionConfig(
                        path=emotion.path,
                        ref_text=emotion.ref_text,
                        speaker_audio_path=emotion.speaker_audio_path,
                    )
                    for name, emotion in char.tts.emotions.items()
                },
            ),
        )

    async def load_from_config(self, config: XnneHangLabSettings) -> None:
        """根据配置重载运行时上下文。

        由于已经移除了 `lab.toml` 中的角色 fallback，
        当前激活的 `memory_agent_profile` 必须存在且必须包含 `[character]`。

        Args:
            config: 最新的实验室配置。

        Raises:
            ValueError: 当 active profile 未配置、加载失败或缺少 `[character]` 时抛出。
        """
        self.lab_setting = config

        if self.server_config is None:
            self.server_config = config.server

        profile_path_str = config.agent.memory_agent_profile
        if not profile_path_str:
            raise ValueError("memory_agent_profile is not configured")

        profile = self._load_active_profile(config)
        if profile is None:
            raise ValueError(f"Failed to load active profile: {profile_path_str}")

        profile_id = Path(profile_path_str).stem
        self.character_config = self._to_character_settings(profile, profile_id=profile_id)
        if self.character_config is None:
            raise ValueError(f"Active memory_agent_profile must define [character]: {profile_path_str}")

        live2d_name = self.character_config.live2d_model_name
        if live2d_name:
            t0 = time.perf_counter()
            logger.info("⏳ 初始化 Live2D...")
            self.init_live2d(live2d_name)
            logger.info("✅ Live2D 初始化完成 ({:.1f}s)", time.perf_counter() - t0)
        else:
            logger.info("ℹ️ 当前 profile 未配置 Live2D 模型，跳过 Live2D 初始化")
            self.live2d_model = None

        t1 = time.perf_counter()
        logger.info("⏳ 初始化 Agent（加载 plugins / LLM client）...")
        await self.init_agent(config)
        logger.info("✅ Agent 初始化完成 ({:.1f}s)", time.perf_counter() - t1)

        self.init_translate(config)
        self.server_config = config.server

    def init_live2d(self, live2d_model_name: str | None) -> None:
        """初始化 Live2D 模型。

        Args:
            live2d_model_name: Live2D 模型名；为空时跳过初始化。
        """
        logger.info("Initializing Live2D: {}", live2d_model_name)
        if not live2d_model_name:
            self.live2d_model = None
            self.live2d_startup_expression_applied = False
            if self.character_config is not None:
                self.character_config.live2d_model_name = ""
            logger.info("Current profile does not configure Live2D, skipping initialization.")
            return

        try:
            self.live2d_model = Live2dModel(live2d_model_name)
            if self.character_config is not None:
                self.character_config.live2d_model_name = live2d_model_name
            self.live2d_startup_expression_applied = False
        except Exception as exc:
            logger.critical("Error initializing Live2D: {}", exc)
            logger.critical("Try to proceed without Live2D...")
            self.live2d_model = None

    async def init_agent(self, lab_settings: XnneHangLabSettings) -> None:
        """初始化 Agent 引擎。

        Args:
            lab_settings: 当前实验室配置。

        Raises:
            ValueError: 当 `character_config` 尚未准备好时抛出。
        """
        if self.character_config is None:
            logger.error("character_config is None, cannot create agent.")
            raise ValueError("character_config cannot be None")

        self.agent_engine = await AgentFactory.create_agent(
            lab_setting=lab_settings,
            live2d_model=self.live2d_model,
            tts_preprocessor_config=self.character_config.tts_preprocessor_config,
        )

    async def reload_runtime_from_current_settings(self) -> None:
        """Rebuild the shared default runtime state in place."""
        previous_agent = self.agent_engine
        if previous_agent is not None:
            await previous_agent.close()
            self.agent_engine = None
            self._mcp_connected = False

        new_context = ServiceContext(self.lab_setting.model_copy(deep=True))
        try:
            await new_context.load_from_config(new_context.lab_setting)
            await new_context.ensure_mcp_connected()
        except Exception:
            if new_context.agent_engine is not None:
                await new_context.agent_engine.close()
                new_context.agent_engine = None
            raise

        if new_context.server_config is None or new_context.agent_engine is None:
            raise ValueError("Reloaded context is incomplete")

        self.load_cache(
            lab_setting=new_context.lab_setting,
            server_config=new_context.server_config,
            character_config=new_context.character_config,
            live2d_model=new_context.live2d_model,
            agent_engine=new_context.agent_engine,
        )
        self._mcp_connected = new_context._mcp_connected
        self.chat_system_prompt = new_context.chat_system_prompt
        self.vision_system_prompt = new_context.vision_system_prompt
        self.history_uid = ""
        self.live2d_startup_expression_applied = new_context.live2d_startup_expression_applied

    async def ensure_mcp_connected(self) -> None:
        """确保 MCP 连接只初始化一次。"""
        if self._mcp_connected or self.agent_engine is None:
            return
        async with self._mcp_lock:
            if self._mcp_connected:
                return
            if self.lab_setting.agent.enable_tool:
                await self.agent_engine.connect_mcp_servers()
            self._mcp_connected = True

    def init_translate(self, lab_settings: XnneHangLabSettings) -> None:
        """初始化或更新翻译引擎。

        Args:
            lab_settings: 当前实验室配置。
        """
        if self.translate_engine is None:
            self.translate_engine = TranslateEngineRouter(lab_settings)
            return

        self.translate_engine.update_settings(lab_settings)

    def get_current_mood_score(self) -> int | None:
        """Return the current mood score from the active mood hook, if present."""
        agent_engine = self.agent_engine
        agent_core = getattr(agent_engine, "core", None)
        hook_manager = getattr(agent_core, "_hook_manager", None)
        hooks = getattr(hook_manager, "_hooks", [])

        for hook in hooks:
            mood_score = getattr(hook, "mood_score", None)
            if isinstance(mood_score, int):
                return max(0, min(100, mood_score))

        return None

    async def send_current_mood(self, websocket_send: WebSocketSend) -> None:
        """Push the current mood score to the frontend if mood support is active."""
        mood_score = self.get_current_mood_score()
        if mood_score is None:
            return

        await websocket_send(
            json.dumps(
                {
                    "type": "mood-update",
                    "score": mood_score,
                }
            )
        )

    def _get_live2d_idle_runtime_config(self) -> tuple[dict[str, dict[str, object]], str]:
        """Read live2d idle bank runtime config exported by the live2d_control plugin."""
        agent_engine = self.agent_engine
        agent_core = getattr(agent_engine, "core", None)
        agent_context = getattr(agent_core, "agent_context", None)
        raw_extra = getattr(agent_context, "extra", {}) if agent_context is not None else {}
        extra: dict[str, object] = cast("dict[str, object]", raw_extra) if isinstance(raw_extra, dict) else {}

        raw_banks = extra.get("live2d_idle_banks")
        typed_banks: dict[str, dict[str, object]] = {}
        if isinstance(raw_banks, dict):
            banks_map = cast("dict[object, object]", raw_banks)
            for key_obj, value_obj in banks_map.items():
                if not isinstance(key_obj, str) or not isinstance(value_obj, dict):
                    continue
                typed_banks[key_obj] = cast("dict[str, object]", value_obj)

        raw_default_state = extra.get("live2d_idle_default_state")
        default_state = (
            raw_default_state.strip() if isinstance(raw_default_state, str) and raw_default_state else "listening"
        )
        return typed_banks, default_state

    def _get_live2d_mixer_runtime_config(self) -> tuple[dict[str, dict[str, float]], str]:
        """Read live2d mixer weight config exported by the live2d_control plugin."""
        agent_engine = self.agent_engine
        agent_core = getattr(agent_engine, "core", None)
        agent_context = getattr(agent_core, "agent_context", None)
        raw_extra = getattr(agent_context, "extra", {}) if agent_context is not None else {}
        extra: dict[str, object] = cast("dict[str, object]", raw_extra) if isinstance(raw_extra, dict) else {}

        raw_weights = extra.get("live2d_mixer_weights_by_state")
        typed_weights: dict[str, dict[str, float]] = {}
        if isinstance(raw_weights, dict):
            weights_map = cast("dict[object, object]", raw_weights)
            for state_key_obj, state_weights_obj in weights_map.items():
                if not isinstance(state_key_obj, str) or not isinstance(state_weights_obj, dict):
                    continue
                state_name = state_key_obj.strip()
                if not state_name:
                    continue

                normalized_weights: dict[str, float] = {}
                state_weights = cast("dict[object, object]", state_weights_obj)
                for layer_id_obj, raw_weight_obj in state_weights.items():
                    if not isinstance(layer_id_obj, str):
                        continue
                    if isinstance(raw_weight_obj, bool):
                        continue
                    if not isinstance(raw_weight_obj, (int, float)):
                        continue
                    value = float(raw_weight_obj)
                    if not math.isfinite(value) or value < 0:
                        continue
                    layer_id = layer_id_obj.strip()
                    if not layer_id:
                        continue
                    normalized_weights[layer_id] = value

                if normalized_weights:
                    typed_weights[state_name] = normalized_weights

        raw_default_state = extra.get("live2d_idle_default_state")
        default_state = (
            raw_default_state.strip() if isinstance(raw_default_state, str) and raw_default_state else "listening"
        )
        return typed_weights, default_state

    def resolve_live2d_idle_bank(self, state: str | None = None) -> tuple[str, dict[str, object]] | None:
        """Resolve idle bank by requested state with fallback to listening/first available."""
        idle_banks, default_state = self._get_live2d_idle_runtime_config()
        if not idle_banks:
            return None

        candidates = [state or "", default_state]
        for candidate in candidates:
            if candidate and candidate in idle_banks:
                return candidate, idle_banks[candidate]

        first_key = next(iter(idle_banks.keys()), "")
        if not first_key:
            return None
        return first_key, idle_banks[first_key]

    def resolve_live2d_mixer_weights(self, state: str | None = None) -> tuple[str, dict[str, float]] | None:
        """Resolve mixer weights by requested state with fallback to listening/first available."""
        mixer_weights_by_state, default_state = self._get_live2d_mixer_runtime_config()
        if not mixer_weights_by_state:
            return None

        candidates = [state or "", default_state]
        for candidate in candidates:
            if candidate and candidate in mixer_weights_by_state:
                return candidate, mixer_weights_by_state[candidate]

        first_key = next(iter(mixer_weights_by_state.keys()), "")
        if not first_key:
            return None
        return first_key, mixer_weights_by_state[first_key]

    async def send_live2d_idle_bank(self, websocket_send: WebSocketSend, state: str | None = None) -> bool:
        """Push a live2d recorded idle bank message to frontend."""
        resolved = self.resolve_live2d_idle_bank(state)
        if resolved is None:
            return False

        resolved_state, idle_bank = resolved
        await websocket_send(
            json.dumps(
                {
                    "type": "set-live2d-idle-bank",
                    "idle_state": resolved_state,
                    "idle_bank": idle_bank,
                }
            )
        )
        return True

    async def send_live2d_mixer_weights(
        self,
        websocket_send: WebSocketSend,
        mixer_weights: dict[str, float] | None = None,
        mixer_weights_mode: str | None = None,
        mixer_state: str | None = None,
    ) -> None:
        """Push mixer layer weights to frontend (e.g. idle/speech/backend/mouse attention blend ratios)."""
        payload: dict[str, object] = {
            "type": "set-live2d-mixer-weights",
        }
        if isinstance(mixer_weights, dict):
            payload["mixer_weights"] = mixer_weights
        if isinstance(mixer_weights_mode, str) and mixer_weights_mode:
            payload["mixer_weights_mode"] = mixer_weights_mode
        if isinstance(mixer_state, str) and mixer_state:
            payload["idle_state"] = mixer_state

        await websocket_send(json.dumps(payload))

    async def send_live2d_mixer_weights_for_state(
        self, websocket_send: WebSocketSend, state: str | None = None
    ) -> bool:
        """Push state-resolved mixer weights to frontend (reset + patch for deterministic state switching)."""
        resolved = self.resolve_live2d_mixer_weights(state)
        if resolved is None:
            return False

        resolved_state, mixer_weights = resolved
        await self.send_live2d_mixer_weights(
            websocket_send=websocket_send,
            mixer_weights=mixer_weights,
            mixer_weights_mode="reset",
            mixer_state=resolved_state,
        )
        return True

    async def send_live2d_runtime_state(self, websocket_send: WebSocketSend, state: str | None = None) -> None:
        """Push both recorded-idle bank and mixer weight state in one call."""
        await self.send_live2d_idle_bank(websocket_send, state=state)
        await self.send_live2d_mixer_weights_for_state(websocket_send, state=state)

    async def handle_config_switch(
        self,
        websocket: WebSocket,
        config_file_name: str,
    ) -> None:
        """处理配置切换并通知前端。

        Args:
            websocket: 当前 WebSocket 连接。
            config_file_name: 目标配置文件名。

        Raises:
            ValueError: 当配置切换请求非法时抛出。
        """
        try:
            if self.server_config is None:
                logger.error("server_config is None, cannot switch configuration")
                raise ValueError("server_config cannot be None")
            if config_file_name != "lab.toml":
                raise ValueError("Only lab.toml is supported")

            new_config = load_settings_file("lab.toml", XnneHangLabSettings)
            await self.load_from_config(new_config)
            logger.debug("New config: {}", self)
            if self.character_config is not None:
                logger.debug("New character config: {}", self.character_config.model_dump())

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "set-model-and-conf",
                        "model_info": (
                            {
                                **self.live2d_model.model_info,
                                "renderScale": self.lab_setting.server.live2d_render_scale,
                            }
                            if self.live2d_model
                            else None
                        ),
                        "conf_name": self.character_config.character_name if self.character_config else "",
                        "conf_uid": self.character_config.profile_id if self.character_config else "",
                    }
                )
            )
            await self.send_live2d_runtime_state(websocket.send_text, state="listening")

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "config-switched",
                        "message": "Switched to config: lab.toml",
                    }
                )
            )

            await self.send_current_mood(websocket.send_text)

            logger.info("Configuration switched to lab.toml")

        except Exception as exc:
            logger.error("Error switching configuration: {}", exc)
            logger.debug(self)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error switching configuration: {str(exc)}",
                    }
                )
            )
            raise
