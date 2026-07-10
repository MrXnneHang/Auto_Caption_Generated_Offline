"""记忆管线插件（wikimem 后端）。

ADR-0001 落地：`on_before_turn` 同步召回（BM25 + 可选 embedding 融合，
0 次 LLM 调用，fail-open）；`on_after_turn` 单次 LLM 抽取，后台任务执行，
永不阻塞对话。事实源是 workspace 下的 markdown 分类文件（人可读可改）。

抽取 LLM 默认继承 lab.toml 的 chat 模型配置；三个 extraction_* 字段留空即
继承，填了就用独立端点（更便宜/本地模型）。embedding_* 留空 = 纯 BM25。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from loguru import logger
from pydantic import Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.hook import HookPlugin

if TYPE_CHECKING:
    from wikimem import MemoryIndex, MemoryStore

    from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM
    from lab.tools.types import AgentContext


class WikimemPluginConfig(PluginConfigModel):
    memory_dir: Annotated[str, Field("memory", description="记忆目录（相对 workspace_root，或绝对路径）")]
    user_id: Annotated[str, Field("xnne", description="记忆条目 owner 标识")]
    search_limit: Annotated[int, Field(10, ge=1, le=100, description="每轮召回的最大命中条数")]
    budget_tokens: Annotated[int, Field(800, ge=100, le=8000, description="每轮注入记忆的 token 预算")]
    extraction_base_url: Annotated[str, Field("", description="抽取 LLM base_url；留空 = 继承 chat 模型配置")]
    extraction_model: Annotated[str, Field("", description="抽取 LLM 模型名；留空 = 继承 chat 模型配置")]
    extraction_api_key: Annotated[str, Field("", description="抽取 LLM API key；留空 = 继承 chat 模型配置")]
    embedding_base_url: Annotated[str, Field("", description="embedding 端点 base_url；留空 = 纯 BM25")]
    embedding_model: Annotated[str, Field("", description="embedding 模型名；留空 = 纯 BM25")]
    embedding_api_key: Annotated[str, Field("", description="embedding API key（可选）")]


PLUGIN_CONFIG_MODEL = WikimemPluginConfig

_EXTRACTION_SYSTEM = """\
你是记忆抽取器。从这轮对话中提取值得长期记住的信息，输出 JSON 数组。

规则：
- 每条自包含：单独读也能懂，与对话相同语言
- 排除短时效信息（天气、临时状态、寒暄、正在进行的任务细节）
- 区分叙述者：用户说的记为用户的事实；助手自己的设定/承诺才记为助手的
- category 用小写英文 slug（参考：preferences / daily_life / profile / event /
  knowledge / behavior / skill / tool，可新建）
- name 简短且稳定（可用中文），不含 : | # [[ ]] 字符
- 内容与"已有条目"相关时，在内容中写入内联链接 [[category:name]]
- 没有值得记的就输出 []

严格输出 JSON 数组（不要代码块、不要解释）：
[{"category": "preferences", "name": "喜欢海边", "content": "喜欢海边，想去海边玩。[[daily_life:海边旅行计划]]"}]
"""

_MAX_ITEMS_PER_TURN = 8


def parse_extraction(text: str) -> list[dict[str, str]]:
    """宽容地从 LLM 输出中解出条目数组：容忍代码块包裹与前后杂讯。"""
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw: Any = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in cast("list[Any]", raw):
        if not isinstance(entry, dict):
            continue
        entry_map = cast("dict[str, Any]", entry)
        category = entry_map.get("category")
        name = entry_map.get("name")
        content = entry_map.get("content")
        if isinstance(category, str) and isinstance(name, str) and isinstance(content, str):
            items.append({"category": category, "name": name, "content": content})
    return items


class WikimemPlugin(HookPlugin):
    config_model = WikimemPluginConfig

    def __init__(
        self,
        memory_dir: str = "memory",
        user_id: str = "xnne",
        search_limit: int = 10,
        budget_tokens: int = 800,
        extraction_base_url: str = "",
        extraction_model: str = "",
        extraction_api_key: str = "",
        embedding_base_url: str = "",
        embedding_model: str = "",
        embedding_api_key: str = "",
        llm: AsyncLLM | None = None,
    ) -> None:
        self._memory_dir = memory_dir
        self._user_id = user_id
        self._search_limit = search_limit
        self._budget_tokens = budget_tokens
        self._extraction_base_url = extraction_base_url.strip()
        self._extraction_model = extraction_model.strip()
        self._extraction_api_key = extraction_api_key.strip()
        self._embedding_base_url = embedding_base_url.strip()
        self._embedding_model = embedding_model.strip()
        self._embedding_api_key = embedding_api_key.strip()
        self._llm: AsyncLLM | None = llm
        self._store: MemoryStore | None = None
        self._index: MemoryIndex | None = None
        self._pending: set[asyncio.Task[None]] = set()
        self._related_names: list[str] = []

    # ------------------------------------------------------------------ setup

    def _ensure_store(self, ctx: AgentContext) -> tuple[MemoryStore, MemoryIndex]:
        if self._store is not None and self._index is not None:
            return self._store, self._index
        from wikimem import MemoryIndex, MemoryStore

        configured = Path(self._memory_dir)
        root = configured if configured.is_absolute() else ctx.workspace_root / configured
        store = MemoryStore(root)
        embedder = None
        if self._embedding_base_url and self._embedding_model:
            from wikimem.vectors import HttpEmbedder

            embedder = HttpEmbedder(
                self._embedding_base_url,
                self._embedding_model,
                api_key=self._embedding_api_key or None,
            )
        index = MemoryIndex(store, embedder=embedder)
        self._store, self._index = store, index
        return store, index

    def _get_llm(self) -> AsyncLLM:
        if self._llm is not None:
            return self._llm
        from lab.agent.stateless_llm_factory import LLMFactory

        if self._extraction_base_url and self._extraction_model:
            self._llm = LLMFactory.create_llm(
                model=self._extraction_model,
                base_url=self._extraction_base_url,
                llm_api_key=self._extraction_api_key or "no-key",
            )
            return self._llm
        # 留空 = 继承 chat 模型配置（独立加载 lab.toml，避免 import server）
        from lab.config_manager.config import XnneHangLabSettings, load_settings_file

        settings = load_settings_file("lab.toml", XnneHangLabSettings)
        chat_model = settings.agent.chat_model
        provider = settings.agent.llm.get_provider_config(chat_model.llm_provider)
        self._llm = LLMFactory.create_llm(
            model=chat_model.llm_model_name,
            base_url=provider.llm_base_url,
            llm_api_key=provider.llm_api_key,
        )
        return self._llm

    # ------------------------------------------------------------------ hooks

    async def on_before_turn(self, user_text: str, ctx: AgentContext) -> str | None:
        try:
            _, index = self._ensure_store(ctx)
            result = index.retrieve(
                user_text,
                limit=self._search_limit,
                budget_tokens=self._budget_tokens,
            )
            self._related_names = [f"{r.item.category}:{r.item.name}" for r in result.items]
            if not result.items:
                return None
            lines = [f"- [{r.item.category}:{r.item.name}] {r.item.content}" for r in result.items]
            return "\n".join(lines)
        except Exception as exc:  # fail-open：召回失败不影响对话
            logger.warning("[Wikimem] retrieve failed, injecting nothing: {}", exc)
            return None

    async def on_after_turn(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        # 抽取是后台任务：本 hook 立即返回，永不阻塞下一轮（ADR-0001 硬约束 2）。
        task = asyncio.create_task(self._memorize(user_text, assistant_text, ctx))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def flush(self) -> None:
        """等待所有后台抽取完成（测试与优雅退出用）。"""
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)

    # -------------------------------------------------------------- memorize

    async def _memorize(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        try:
            store, _ = self._ensure_store(ctx)
            from lab.agent.types import OpenAIMessage

            categories = ", ".join(store.categories()) or "（暂无）"
            related = ", ".join(self._related_names) or "（无）"
            prompt = (
                f"已有分类：{categories}\n"
                f"本轮相关的已有条目（可作为 [[链接]] 目标）：{related}\n\n"
                f"对话：\n用户：{user_text}\n助手：{assistant_text}"
            )
            llm = self._get_llm()
            chunks: list[str] = []
            async for chunk in llm.chat_completion(
                messages=[OpenAIMessage(role="user", content=prompt)],
                system=_EXTRACTION_SYSTEM,
                stream_=False,
            ):
                chunks.append(chunk)
            items = parse_extraction("".join(chunks))
            stored = 0
            for item in items[:_MAX_ITEMS_PER_TURN]:
                try:
                    store.add(
                        item["category"],
                        item["name"],
                        item["content"],
                        owner=self._user_id,
                    )
                    stored += 1
                except ValueError as exc:  # 非法 slug/名字：跳过该条，不失败整轮
                    logger.warning("[Wikimem] skipped invalid item {}: {}", item.get("name"), exc)
            if stored:
                logger.info("[Wikimem] memorized {} item(s)", stored)
        except Exception as exc:  # 抽取失败 = 本轮不记忆，绝不影响对话
            logger.warning("[Wikimem] memorize skipped: {}", exc)
