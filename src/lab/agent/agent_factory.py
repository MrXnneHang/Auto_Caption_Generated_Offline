from __future__ import annotations

import asyncio
import inspect
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from lab.agent.agents.memory_agent import MemoryAgent
from lab.agent.core import AgentCore
from lab.agent.hook_manager import HookManager
from lab.agent.stateless_llm_factory import LLMFactory
from lab.plugin.loader import PluginLoader
from lab.profile.context_injector import ContextInjector
from lab.profile.schema import Profile
from lab.profile.system_prompt_builder import SystemPromptBuilder
from lab.tools import (
    AgentContext,
    EditFileTool,
    GetDatetimeTool,
    ListDirTool,
    ReadFileTool,
    ToolManager,
    WriteFileTool,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from lab.agent.agents.agent_interface import AgentInterface
    from lab.agent.storage import ConversationStorage
    from lab.config_manager import XnneHangLabSettings
    from lab.config_manager.package import Packages
    from lab.config_manager.vtuber import TTSPreprocessorConfig
    from lab.live2d_model import Live2dModel
    from lab.tools.plugin import PromptSegment


def build_default_tool_manager(workspace_root: Path) -> ToolManager:
    del workspace_root

    tm = ToolManager()
    tm.register_builtin(GetDatetimeTool())
    tm.register_builtin(ReadFileTool())
    tm.register_builtin(WriteFileTool())
    tm.register_builtin(EditFileTool())
    tm.register_builtin(ListDirTool())
    return tm


class AgentFactory:
    @staticmethod
    async def create_core_with_profile(
        lab_setting: XnneHangLabSettings,
        profile_path: Path,
        storage: ConversationStorage,
        vision_system_prompt: str = "",
        workspace_root: Path | None = None,
        packages: Packages | None = None,
        live2d_model: Live2dModel | None = None,
    ) -> AgentCore:
        chat_model = lab_setting.agent.chat_model
        vision_model = lab_setting.agent.vision_model

        ws_root = workspace_root or Path.cwd()
        profile = Profile.from_toml(profile_path)

        live2d_appearance_presets: list[dict[str, str]] = []
        live2d_preset_expressions: list[dict[str, Any]] = []
        live2d_motion_assets: list[dict[str, Any]] = []
        live2d_imported_motions: list[dict[str, Any]] = []
        if live2d_model is not None:
            raw_appearance_presets = live2d_model.model_info.get("appearancePresets")
            if isinstance(raw_appearance_presets, list):
                live2d_appearance_presets = cast("list[dict[str, str]]", raw_appearance_presets)
            raw_expressions = live2d_model.model_info.get("_preset_expressions")
            if isinstance(raw_expressions, list):
                live2d_preset_expressions = cast("list[dict[str, Any]]", raw_expressions)
            raw_motion_assets = live2d_model.model_info.get("motionAssets")
            if isinstance(raw_motion_assets, list):
                live2d_motion_assets = cast("list[dict[str, Any]]", raw_motion_assets)
            raw_imported_motions = live2d_model.model_info.get("importedMotions")
            if isinstance(raw_imported_motions, list):
                live2d_imported_motions = cast("list[dict[str, Any]]", raw_imported_motions)

        agent_context = AgentContext(
            workspace_root=ws_root,
            extra={
                "live2d_emo_map": live2d_model.emo_map if live2d_model else {},
                "live2d_appearance_presets": live2d_appearance_presets,
                "live2d_preset_expressions": live2d_preset_expressions,
                "live2d_motion_assets": live2d_motion_assets,
                "live2d_imported_motions": live2d_imported_motions,
            },
        )

        def _read_prompt(path_str: str) -> str:
            path = Path(path_str)
            if not path.is_absolute():
                path = ws_root / path_str
            return path.read_text(encoding="utf-8").strip() if path.exists() else ""

        resolved_vision_prompt = vision_system_prompt or _read_prompt(lab_setting.agent.prompts.vision_prompt)

        plugin_loader = PluginLoader()
        tool_plugins, skill_descriptors, hook_plugins, policy_plugins = await plugin_loader.load_many(
            profile.plugins.enabled,
            profile_overrides=profile.plugins.overrides,
            ctx=agent_context,
        )

        tool_manager = build_default_tool_manager(ws_root)
        for tool_plugin in tool_plugins:
            for builtin_tool in tool_plugin.get_tools():
                tool_manager.register_builtin(builtin_tool)

        tool_prompt_segments: list[PromptSegment] = []
        for policy_plugin in policy_plugins:
            tool_prompt_segments.extend(policy_plugin.get_prompt_segments())
        for tool_plugin in tool_plugins:
            tool_prompt_segments.extend(tool_plugin.get_prompt_segments())

        registered_tool_names = {
            name for schema in tool_manager.list_tools_schema() if (name := schema.get("function", {}).get("name"))
        }
        for skill in skill_descriptors:
            missing = [required_tool for required_tool in skill.requires if required_tool not in registered_tool_names]
            if missing:
                raise ValueError(
                    f"Skill '{skill.id}' requires tools {missing}, "
                    "but they are not registered. "
                    "Add the required ToolPlugin to profile.plugins.enabled."
                )

        for hook in hook_plugins:
            req_pkg = getattr(hook, "_requires_package", None)
            if req_pkg and not (packages or {}).get(req_pkg, False):
                raise ValueError(
                    f"Profile enabled '{hook.__class__.__name__}' plugin, "
                    f"but lab.toml [package].{req_pkg} = false.\n"
                    f"Set {req_pkg} = true and make sure the backend service is installed."
                )

        hook_manager = HookManager()
        for hook in hook_plugins:
            hook_manager.register(hook)

        chat_llm = lab_setting.agent.llm.get_provider_config(chat_model.llm_provider)
        vision_llm = lab_setting.agent.llm.get_provider_config(vision_model.llm_provider)

        chat_llm_interface = LLMFactory.create_llm(
            model=chat_model.llm_model_name,
            base_url=chat_llm.llm_base_url,
            llm_api_key=chat_llm.llm_api_key,
        )
        vision_llm_interface = None
        if not vision_model.llm_model_name.strip() or not vision_llm.llm_base_url.strip():
            logger.warning(
                "[VISION] vision analysis unavailable: vision model configuration is incomplete. "
                "model='{}' base_url='{}'",
                vision_model.llm_model_name,
                vision_llm.llm_base_url,
            )
        else:
            try:
                vision_llm_interface = LLMFactory.create_llm(
                    model=vision_model.llm_model_name,
                    base_url=vision_llm.llm_base_url,
                    llm_api_key=vision_llm.llm_api_key,
                )
            except Exception as exc:
                logger.warning("[VISION] vision analysis unavailable: failed to initialize vision model: {}", exc)

        # Generate expression list for format prompt injection
        format_variables: dict[str, str] = {}
        if live2d_preset_expressions:
            expression_lines: list[str] = []
            for exp in live2d_preset_expressions:
                if exp.get("role") != "expression":
                    continue
                label = exp.get("label", exp.get("name", ""))
                description = exp.get("description", "")
                if description:
                    expression_lines.append(f"- [expression:{label}] — {description}")
                else:
                    expression_lines.append(f"- [expression:{label}]")
            # Always include a neutral/reset entry at the top (if not already present)
            has_neutral = any("平静" in line for line in expression_lines)
            if not has_neutral:
                expression_lines.insert(
                    0, "- [expression:平静] — 日常对话、平稳陈述、没有特别情绪的场合（清除当前表情）"
                )
            expression_list_str = "\n".join(expression_lines)
            format_variables["EXPRESSION_LIST"] = expression_list_str
            logger.info("===== Expression List =====\n{}\n===== End Expression List =====", expression_list_str)

        # Generate TTS emotion list from voice config
        voice_id = (
            profile.character.tts.voice if profile.character is not None and profile.character.tts.voice else None
        )
        if voice_id:
            voice_config_path = ws_root / "config" / "voices" / f"{voice_id}.toml"
            if voice_config_path.is_file():
                with voice_config_path.open("rb") as vf:
                    voice_payload: dict[str, Any] = tomllib.load(vf)
                emotions_section = voice_payload.get("emotions")
                if isinstance(emotions_section, dict) and emotions_section:
                    tts_lines: list[str] = []
                    for emotion_key, emotion_data in cast("dict[str, Any]", emotions_section).items():
                        description = ""
                        if isinstance(emotion_data, dict):
                            raw_desc = cast("dict[str, Any]", emotion_data).get("description")
                            description = str(raw_desc) if raw_desc else ""
                        if description:
                            tts_lines.append(f"- [tts:{emotion_key}] — {description}")
                        else:
                            tts_lines.append(f"- [tts:{emotion_key}]")
                    tts_list_str = "\n".join(tts_lines)
                    format_variables["TTS_EMOTION_LIST"] = tts_list_str
                    logger.info("===== TTS Emotion List =====\n{}\n===== End TTS Emotion List =====", tts_list_str)

        chat_system_prompt = SystemPromptBuilder(ws_root).build(
            persona_path=profile.prompt.persona,
            format_path=profile.prompt.format,
            skills=skill_descriptors,
            tool_manager=tool_manager,
            tool_prompt_segments=tool_prompt_segments,
            character_name=profile.character.character_name if profile.character else "",
            format_variables=format_variables or None,
        )
        logger.info(
            "===== Chat System Prompt Preview ({}) =====\n{}\n===== End Chat System Prompt Preview =====",
            profile.character.character_name if profile.character else "",
            chat_system_prompt,
        )

        core = AgentCore(
            chat_llm=chat_llm_interface,
            vision_llm=vision_llm_interface,
            tool_manager=tool_manager,
            agent_context=agent_context,
            context_injector=ContextInjector(),
            storage=storage,
            chat_system_prompt=chat_system_prompt,
            vision_system_prompt=resolved_vision_prompt,
            enable_tool=lab_setting.agent.enable_tool,
            max_vision_concurrency=lab_setting.agent.max_vision_concurrency,
            require_detailed=lab_setting.agent.require_detailed,
            hook_manager=hook_manager,
        )
        core.chat_supports_vision = lab_setting.agent.chat_model.support_vision
        return core

    @staticmethod
    async def create_agent(
        lab_setting: XnneHangLabSettings,
        live2d_model: Live2dModel | None = None,
        tts_preprocessor_config: TTSPreprocessorConfig | None = None,
        workspace_root: Path | None = None,
    ) -> AgentInterface:
        from lab.agent.agents.memory_agent.memory_store import MemoryStore
        from lab.agent.storage import MemoryStoreAdapter

        ws_root = workspace_root or Path.cwd()

        profile_path_str = lab_setting.agent.memory_agent_profile
        if not profile_path_str:
            raise ValueError(
                "lab_setting.agent.memory_agent_profile is not configured. "
                'Set memory_agent_profile = "profiles/xxx.toml" in [agent].'
            )
        profile_path = Path(profile_path_str)
        if not profile_path.is_absolute():
            profile_path = ws_root / profile_path_str
        if not profile_path.exists():
            raise FileNotFoundError(f"memory_agent_profile not found: {profile_path}")
        profile = Profile.from_toml(profile_path)

        memory_store = MemoryStore()
        storage = MemoryStoreAdapter(
            memory_store,
            condense_after_turns=lab_setting.agent.structured_history_full_turns,
        )

        core = await AgentFactory.create_core_with_profile(
            lab_setting=lab_setting,
            profile_path=profile_path,
            storage=storage,
            workspace_root=ws_root,
            packages=lab_setting.package.to_dict(),
            live2d_model=live2d_model,
        )

        agent = MemoryAgent(
            lab_settings=lab_setting,
            core=core,
            live2d_model=live2d_model,
            tts_preprocessor_config=tts_preprocessor_config,
            show_control_tags=profile.prompt.show_control_tags,
            faster_first_response=lab_setting.agent.faster_first_response,
            segment_method=lab_setting.agent.segment_method,
            interrupt_method=lab_setting.agent.interrupt_method,
        )
        agent.memory = memory_store
        agent_context = core.agent_context
        if agent_context is None:
            raise ValueError("AgentCore.agent_context must be available when creating a MemoryAgent.")
        agent_context.extra["agent"] = agent

        original_close = agent.close

        async def _close_with_hooks() -> None:
            hook_manager = getattr(core, "_hook_manager", None)
            hooks = getattr(hook_manager, "_hooks", []) if hook_manager is not None else []
            stop_awaitables: list[tuple[object, Awaitable[Any]]] = []
            for hook in hooks:
                stop = getattr(hook, "stop", None)
                if stop is None:
                    continue
                try:
                    result = stop()
                except Exception as exc:
                    logger.warning("Hook plugin stop failed for {}: {}", hook.__class__.__name__, exc)
                    continue
                if inspect.isawaitable(result):
                    stop_awaitables.append((hook, result))

            if stop_awaitables:
                results: list[Any] = list(
                    await asyncio.gather(*(result for _, result in stop_awaitables), return_exceptions=True)
                )
                for (hook, _), result in zip(stop_awaitables, results, strict=False):
                    if isinstance(result, Exception):
                        logger.warning("Hook plugin stop failed for {}: {}", hook.__class__.__name__, result)

            await original_close()

        agent.close = _close_with_hooks  # ty: ignore[invalid-assignment]
        return agent
