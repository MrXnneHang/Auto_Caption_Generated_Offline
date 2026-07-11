from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from lab.config_manager import XnneHangLabSettings, load_settings_file
from lab.service_context import ServiceContext

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from loguru import Logger

lab_settings: XnneHangLabSettings = load_settings_file("lab.toml", XnneHangLabSettings)
_T = TypeVar("_T")

ROOT_DIR = Path(lab_settings.root.root_dir) / "static"

if not ROOT_DIR.exists():
    raise FileNotFoundError(f"Static root directory {ROOT_DIR} does not exist.")


class AvatarStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        """限制头像目录只允许访问图片资源。

        Args:
            path: 请求的相对路径。
            scope: Starlette 请求作用域。

        Returns:
            Response: 合法图片返回文件响应，否则返回 403。

        Raises:
            None.
        """
        allowed_extensions = (".jpg", ".jpeg", ".png", ".gif", ".svg")
        if not any(path.lower().endswith(ext) for ext in allowed_extensions):
            return Response("Forbidden file type", status_code=403)
        return await super().get_response(path, scope)


def _include_router_with_log(name: str, include: Callable[[], None]) -> None:
    """统一记录路由注册耗时。

    Args:
        name: 路由或初始化阶段名称。
        include: 实际执行注册的回调。

    Returns:
        None.

    Raises:
        None.
    """
    started = time.perf_counter()
    logger.info("⏳ 初始化 {}...", name)
    include()
    logger.info("✅ {} 初始化完成 ({:.1f}s)", name, time.perf_counter() - started)


async def _run_blocking(func: Callable[[], _T]) -> _T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func)


async def _run_startup_step(
    start_message: str,
    func: Callable[[], _T],
    *,
    success_message: str | None = None,
    success_handler: Callable[[Logger, float, _T], None] | None = None,
    step_logger: Logger = logger,
) -> _T:
    started = time.perf_counter()
    step_logger.info(start_message)
    result = await _run_blocking(func)
    elapsed = time.perf_counter() - started
    if success_handler is not None:
        success_handler(step_logger, elapsed, result)
    elif success_message is not None:
        step_logger.info(success_message, elapsed)
    return result


def _log_qwen_asr_startup_result(step_logger: Logger, elapsed: float, loaded_models: Sequence[str]) -> None:
    if loaded_models:
        step_logger.info(f"✅ Qwen3-ASR 引擎预加载完成 ({elapsed:.1f}s, models={','.join(loaded_models)})")
    else:
        step_logger.warning("Qwen3-ASR service is enabled, but `asr.qwen_asr.preload_models` is empty.")


def _log_llm_translate_startup_result(step_logger: Logger, elapsed: float, loaded: bool) -> None:
    if loaded:
        step_logger.info(f"✅ LLM Translate 后端初始化完成 ({elapsed:.1f}s)")
    else:
        step_logger.warning("LLM Translate service is enabled, but `agent.translate.llm.model_path` is empty.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理 FastAPI 生命周期中的预加载逻辑。

    Args:
        app: FastAPI 应用实例。

    Returns:
        None.

    Raises:
        ValueError: `/memory/chat` 缺少关键配置时抛出。
    """
    if lab_settings.asr.asr_model_provider == "sherpa":
        from lab.api.logic.sherpa_asr import load_sherpa_asr

        await _run_startup_step(
            "Preloading Sherpa-ONNX ASR/VAD engines...",
            load_sherpa_asr,
            success_message="Sherpa-ONNX ASR/VAD preload finished ({:.1f}s)",
        )

    if lab_settings.asr.asr_model_provider == "qwen":
        from lab.api.logic.qwen_asr import preload_configured_qwen_asr_engines

        await _run_startup_step(
            "Preloading Qwen3-ASR engines...",
            preload_configured_qwen_asr_engines,
            success_handler=_log_qwen_asr_startup_result,
        )

    if lab_settings.agent.tts.provider == "qwen_tts":
        from lab.api.logic.faster_qwen_tts import load_qwen_tts_model

        await _run_startup_step(
            "Loading Qwen-TTS model...",
            load_qwen_tts_model,
            success_message="Qwen-TTS model loaded and warmed up ({:.1f}s)",
            step_logger=logger.bind(group="tts"),
        )

    if lab_settings.agent.tts.provider == "genie_tts":
        from lab.api.logic.genie_tts import load_genie_tts_model, warmup_genie_tts_model

        genie_logger = logger.bind(group="tts")
        genie_started = time.perf_counter()
        genie_logger.info("Loading Genie-TTS model...")
        await _run_blocking(load_genie_tts_model)
        await warmup_genie_tts_model()
        genie_logger.info(f"Genie-TTS model loaded and warmed up ({time.perf_counter() - genie_started:.1f}s)")

    if lab_settings.agent.tts.provider == "gsv_lite":
        from lab.api.logic.gsv_lite import load_gsv_lite_model, warmup_gsv_lite_model

        gsv_lite_logger = logger.bind(group="tts")
        gsv_lite_started = time.perf_counter()
        gsv_lite_logger.info("Loading GSV-Lite model...")
        await _run_blocking(load_gsv_lite_model)
        await warmup_gsv_lite_model()
        gsv_lite_logger.info(f"GSV-Lite model loaded and warmed up ({time.perf_counter() - gsv_lite_started:.1f}s)")

    if lab_settings.package.llm_translate:
        from lab.api.logic.llm_translate import preload_configured_llm_translate_engine

        await _run_startup_step(
            "⏳ 初始化 LLM Translate 后端...",
            preload_configured_llm_translate_engine,
            success_handler=_log_llm_translate_startup_result,
        )

    if lab_settings.package.local_embedding:
        from lab.api.logic.embedding import load_embedding_model

        await _run_startup_step(
            "⏳ 预加载本地 Embedding 模型...",
            partial(
                load_embedding_model,
                model_path=lab_settings.local_embedding.model_path,
                pooling_type=lab_settings.local_embedding.pooling_type,
                n_gpu_layers=lab_settings.local_embedding.n_gpu_layers,
            ),
            success_message="✅ 本地 Embedding 模型预加载完成 ({:.1f}s)",
        )

    ctx = getattr(app.state, "default_context_cache", None)
    if ctx is not None and lab_settings.agent.enable_tool:
        try:
            logger.info("Application startup: connecting to MCP servers...")
            await ctx.agent_engine.connect_mcp_servers()
            logger.info("MCP servers connected.")
        except Exception:
            logger.warning("Failed to connect to MCP servers on startup.")
            logger.warning("You may not have started the MCP server yet. Run `just mcp-server` first.")
            logger.warning("If you do not need tool calling, you can ignore this warning or disable `enable_tool`.")
            logger.warning("Application startup will continue, but tool calling is disabled for this run.")

    # /memory/chat 是 lab 自有的 profile 驱动聊天端点（与已移除的 memory_bench 后端无关），
    # 配置了 memory_chat_profile 即启用。
    if lab_settings.agent.memory_chat_profile:
        try:
            chat_started = time.perf_counter()
            logger.info("⏳ 初始化 /memory/chat 端点...")
            from lab.agent.agent_factory import AgentFactory
            from lab.agent.storage import HistoryStorageAdapter
            from lab.api.routes.chat import chat_state
            from lab.history_storage.store import HistoryStorage

            chat_model_cfg = lab_settings.agent.chat_model
            ws_root = Path(lab_settings.root.root_dir)
            chat_state.chat_model = chat_model_cfg.llm_model_name
            chat_state.workspace_root = str(ws_root)
            chat_state.history_storage_dir = str(ws_root / "data" / "conversations")

            chat_profile_path_str = lab_settings.agent.memory_chat_profile
            chat_profile_path = Path(chat_profile_path_str)
            if not chat_profile_path.is_absolute():
                chat_profile_path = ws_root / chat_profile_path_str
            if not chat_profile_path.exists():
                raise FileNotFoundError(f"memory_chat_profile not found: {chat_profile_path}")

            chat_store = HistoryStorage(base_dir=chat_state.history_storage_dir)
            chat_state.agent_core = await AgentFactory.create_core_with_profile(
                lab_setting=lab_settings,
                profile_path=chat_profile_path,
                storage=HistoryStorageAdapter(
                    chat_store,
                    condense_after_turns=lab_settings.agent.structured_history_full_turns,
                ),
                workspace_root=ws_root,
                packages=lab_settings.package.to_dict(),
            )
            logger.info(
                "✅ /memory/chat 端点初始化完成 ({:.1f}s, profile={})",
                time.perf_counter() - chat_started,
                chat_profile_path_str,
            )
        except ValueError:
            raise
        except Exception as chat_exc:
            logger.warning("Chat endpoint init failed: {}", chat_exc)

    yield

    if lab_settings.package.llm_translate:
        from lab.api.logic.llm_translate import unload_llm_translate_engine

        try:
            unload_llm_translate_engine()
        except Exception as exc:
            logger.warning("LLM Translate cleanup failed: {}", exc)

    if lab_settings.package.local_embedding:
        from lab.api.logic.embedding import unload_embedding_model

        try:
            unload_embedding_model()
        except Exception as exc:
            logger.warning("Local embedding cleanup failed: {}", exc)

    logger.info("Application shutdown: lifespan cleanup completed.")


class WebSocketServer:
    def __init__(self) -> None:
        """创建并初始化 WebSocket/FastAPI 服务。

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        self.app = FastAPI(lifespan=lifespan)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        default_context_cache = ServiceContext()
        asyncio.run(default_context_cache.load_from_config(default_context_cache.lab_setting))
        vtuber_routes = import_module("lab.api.routes.vtuber")
        client_ws_router = vtuber_routes.init_client_ws_route(default_context_cache=default_context_cache)

        _include_router_with_log(
            "/client-ws 端点",
            lambda: self.app.include_router(client_ws_router),
        )
        _include_router_with_log(
            "VTuber 基础端点",
            lambda: self.app.include_router(vtuber_routes.router),
        )
        _include_router_with_log(
            "Runtime Status 端点",
            lambda: self.app.include_router(import_module("lab.api.routes.status").router),
        )
        _include_router_with_log(
            "MBTI 测试端点",
            lambda: self.app.include_router(import_module("lab.api.routes.mbti").router),
        )
        _include_router_with_log(
            "DeepLX 端点",
            lambda: self.app.include_router(import_module("lab.api.routes.deeplx").router),
        )
        if lab_settings.package.llm_translate:
            _include_router_with_log(
                "LLM Translate 端点",
                lambda: self.app.include_router(import_module("lab.api.routes.llm_translate").router),
            )
        if lab_settings.package.local_embedding:
            _include_router_with_log(
                "本地 Embedding 端点",
                lambda: self.app.include_router(import_module("lab.api.routes.embedding").router),
            )
        if lab_settings.asr.asr_model_provider in ("sherpa", "qwen"):
            _include_router_with_log(
                "ASR reload 端点",
                lambda: self.app.include_router(import_module("lab.api.routes.asr_reload").router),
            )
        if lab_settings.asr.asr_model_provider == "sherpa":
            _include_router_with_log(
                "Sherpa-ONNX ASR 端点",
                lambda: self.app.include_router(import_module("lab.api.routes.asr_sherpa").router),
            )
        if lab_settings.asr.asr_model_provider == "qwen":
            _include_router_with_log(
                "Qwen3-ASR 端点",
                lambda: self.app.include_router(import_module("lab.api.routes.asr_qwen").router),
            )
        if lab_settings.agent.tts.provider == "qwen_tts":
            _include_router_with_log(
                "faster-qwen-tts route",
                lambda: self.app.include_router(import_module("lab.api.routes.faster_qwen_tts").router),
            )
        if lab_settings.agent.tts.provider == "genie_tts":
            _include_router_with_log(
                "genie-tts route",
                lambda: self.app.include_router(import_module("lab.api.routes.genie_tts").router),
            )
        if lab_settings.agent.tts.provider == "gsv_lite":
            _include_router_with_log(
                "gsv-lite route",
                lambda: self.app.include_router(import_module("lab.api.routes.gsv_lite").router),
            )
        if lab_settings.agent.memory_chat_profile:
            _include_router_with_log(
                "/memory/chat 路由",
                lambda: self.app.include_router(
                    import_module("lab.api.routes.chat").chat_router,
                    prefix="/memory",
                ),
            )

        logger.info("Mounting static files from {}", ROOT_DIR)
        self.app.mount(
            "/live2d-models",
            StaticFiles(directory=(ROOT_DIR / "live2d-models")),
            name="live2d-models",
        )
        self.app.mount(
            "/bg",
            StaticFiles(directory=str(ROOT_DIR / "backgrounds")),
            name="backgrounds",
        )
        self.app.mount(
            "/avatars",
            AvatarStaticFiles(directory=str(ROOT_DIR / "avatars")),
            name="avatars",
        )
        self.app.state.default_context_cache = default_context_cache
        self.app.state.ws_handler = getattr(client_ws_router, "ws_handler", None)

    def run(self) -> None:
        """预留运行入口。

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        pass
