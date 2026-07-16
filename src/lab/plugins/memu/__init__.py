"""记忆管线插件（memU CLI 后端，实验性）。

上游 pivot（2026-07）：NevaMind-AI/MemU 现在只发布 `memu-cli`（`memu-py` 冻结待归档），
且 CLI 是唯一受支持的集成面——上游明确按「短生命周期进程」设计（memu/env.py）。同时
memU 不再自带 LLM 抽取：`memu commit` 只持久化宿主准备好的 recall files（record seam），
`memu retrieve` 是 0 LLM 的 embedding 检索（inject seam）。

因此本插件的形态是（ADR-0003）：

- 每次调用都用 `uv run --isolated --no-project --python 3.13 --with packages/memU memu ...`
  拉起一个短生命周期子进程（uv 有环境缓存；首次调用触发 maturin 源码构建，需要 Rust）。
  memu-cli 要求 Python 3.13，无法在本项目（3.11）内进程导入。
- `on_before_turn`：`memu retrieve <query>`（stdout JSON）→ 按 token 预算注入 segments。
- `on_after_turn`：后台任务里做单次 LLM 抽取（默认继承 lab.toml chat 配置，与 wikimem
  同一套 category/name/content 契约），把条目按行追加到本地影子 markdown
  （`<memory_dir>/recall/<category>.md`，人可读可改），再把整个文件 `memu commit`——
  memU 按行 diff 重建 segments，未变的行保留 embedding。
- 全程 fail-open：uv/子模块/embedding 配置缺失 → 本会话禁用；单次调用失败 → 本轮跳过。

embedding 端点（OpenAI 兼容）是硬前置：commit 与 retrieve 都要向量化，留空即禁用。
store 通过进程环境变量隔离（MEMU_DB / MEMU_CONFIG_ENV 指向 memory_dir），绝不与用户
全局 `~/.memu/config.env` 串味。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from loguru import logger
from pydantic import Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.hook import HookPlugin
from lab.plugins.wikimem import parse_extraction

if TYPE_CHECKING:
    from lab.agent.stateless_llm.openai_compatible_llm import AsyncLLM
    from lab.tools.types import AgentContext


class MemuPluginConfig(PluginConfigModel):
    memory_dir: Annotated[str, Field("memu_memory", description="memU 状态目录（相对 workspace_root，或绝对路径）")]
    search_limit: Annotated[int, Field(5, ge=1, le=50, description="每轮召回的最大命中条数")]
    budget_tokens: Annotated[int, Field(800, ge=100, le=8000, description="每轮注入记忆的 token 预算")]
    python_version: Annotated[str, Field("3.13", description="memu-cli 子进程的 Python 版本（上游要求 >=3.13）")]
    retrieve_timeout: Annotated[float, Field(15.0, ge=1.0, le=120.0, description="召回超时秒数（超时不注入）")]
    commit_timeout: Annotated[float, Field(600.0, ge=30.0, le=1800.0, description="写入超时秒数（首次含源码构建）")]
    extraction_base_url: Annotated[str, Field("", description="抽取 LLM base_url；留空 = 继承 chat 模型配置")]
    extraction_model: Annotated[str, Field("", description="抽取 LLM 模型名；留空 = 继承 chat 模型配置")]
    extraction_api_key: Annotated[str, Field("", description="抽取 LLM API key；留空 = 继承 chat 模型配置")]
    embedding_base_url: Annotated[str, Field("", description="embedding 端点 base_url（必填；留空则插件禁用）")]
    embedding_model: Annotated[str, Field("text-embedding-3-small", description="embedding 模型名")]
    embedding_api_key: Annotated[str, Field("", description="embedding API key")]


PLUGIN_CONFIG_MODEL = MemuPluginConfig

_EXTRACTION_SYSTEM = """\
你是记忆抽取器。从这轮对话中提取值得长期记住的信息，输出 JSON 数组。

规则：
- 每条自包含：单独读也能懂，与对话相同语言
- 排除短时效信息（天气、临时状态、寒暄、正在进行的任务细节）
- 区分叙述者：用户说的记为用户的事实；助手自己的设定/承诺才记为助手的
- category 用小写英文 slug（参考：preferences / daily_life / profile / event /
  knowledge / behavior / skill / tool，可新建）
- name 简短且稳定（可用中文），不含 : | # 字符
- 没有值得记的就输出 []

严格输出 JSON 数组（不要代码块、不要解释）：
[{"category": "preferences", "name": "喜欢海边", "content": "喜欢海边，想去海边玩。"}]
"""

_MAX_ITEMS_PER_TURN = 8
_CATEGORY_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _category_slug(category: str) -> str:
    """把抽取出的 category 收敛成安全的文件名/recall file 名（空 = 丢弃该条）。"""
    return _CATEGORY_SLUG_RE.sub("-", category.strip().lower()).strip("-")


class MemuPlugin(HookPlugin):
    config_model = MemuPluginConfig

    def __init__(
        self,
        memory_dir: str = "memu_memory",
        search_limit: int = 5,
        budget_tokens: int = 800,
        python_version: str = "3.13",
        retrieve_timeout: float = 15.0,
        commit_timeout: float = 600.0,
        extraction_base_url: str = "",
        extraction_model: str = "",
        extraction_api_key: str = "",
        embedding_base_url: str = "",
        embedding_model: str = "text-embedding-3-small",
        embedding_api_key: str = "",
        llm: AsyncLLM | None = None,
    ) -> None:
        self._memory_dir = memory_dir
        self._search_limit = search_limit
        self._budget_tokens = budget_tokens
        self._python_version = python_version
        self._retrieve_timeout = retrieve_timeout
        self._commit_timeout = commit_timeout
        self._extraction_base_url = extraction_base_url.strip()
        self._extraction_model = extraction_model.strip()
        self._extraction_api_key = extraction_api_key.strip()
        self._embedding_base_url = embedding_base_url.strip()
        self._embedding_model = embedding_model.strip()
        self._embedding_api_key = embedding_api_key.strip()
        self._llm: AsyncLLM | None = llm
        self._disabled = False
        self._disabled_logged = False
        self._pending: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ setup

    def _repo_root(self) -> Path:
        return Path(__file__).parents[4]

    def _data_dir(self, ctx: AgentContext) -> Path:
        configured = Path(self._memory_dir)
        return configured if configured.is_absolute() else ctx.workspace_root / configured

    def _check_enabled(self) -> bool:
        """结构性前置：embedding 配置 + 子模块存在。失败 = 本会话禁用（只警告一次）。"""
        if self._disabled:
            return False
        reason = ""
        if not self._embedding_base_url:
            reason = "embedding_base_url 未配置（memU 的 commit/retrieve 都需要向量化）"
        elif not (self._repo_root() / "packages" / "memU" / "pyproject.toml").exists():
            reason = "packages/memU 子模块缺失（git submodule update --init）"
        if reason:
            self._disabled = True
            if not self._disabled_logged:
                self._disabled_logged = True
                logger.warning("[memU] disabled: {}", reason)
            return False
        return True

    def _memu_env(self, ctx: AgentContext) -> dict[str, str]:
        """record 与 inject 两条 seam 必须共用同一 store + embedding 空间（上游 ADR-0009）。"""
        data_dir = self._data_dir(ctx)
        env = dict(os.environ)
        env["MEMU_DB"] = str(data_dir / "memu.sqlite3")
        # 私有 config.env：默认不存在 = 用户全局 ~/.memu/config.env 绝不串进来
        env["MEMU_CONFIG_ENV"] = str(data_dir / "config.env")
        env["MEMU_EMBED_PROVIDER"] = "openai"
        env["MEMU_BASE_URL"] = self._embedding_base_url
        env["MEMU_API_KEY"] = self._embedding_api_key or "no-key"
        env["MEMU_EMBED_MODEL"] = self._embedding_model or "text-embedding-3-small"
        return env

    async def _run_memu(
        self,
        args: list[str],
        ctx: AgentContext,
        *,
        stdin_payload: str | None = None,
        timeout: float,
    ) -> str:
        """跑一次 `memu <args>` 短生命周期子进程，返回 stdout；任何失败抛异常（由调用方 fail-open）。"""
        submodule = self._repo_root() / "packages" / "memU"
        cmd = [
            "uv", "run", "--isolated", "--no-project", "--python", self._python_version,
            "--with", str(submodule),
            "memu", *args,
        ]  # fmt: skip
        self._data_dir(ctx).mkdir(parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._repo_root()),
                env=self._memu_env(ctx),
                stdin=asyncio.subprocess.PIPE if stdin_payload is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:  # uv 不在 PATH：结构性问题，直接禁用
            self._disabled = True
            logger.warning("[memU] disabled: 未找到 uv，可执行文件不可用")
            raise
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin_payload.encode("utf-8") if stdin_payload is not None else None),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            raise
        if proc.returncode != 0:
            tail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
            raise RuntimeError(f"memu {args[0]} rc={proc.returncode}: {' | '.join(tail)}")
        return stdout.decode("utf-8", errors="replace")

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
            if not self._check_enabled() or not user_text.strip():
                return None
            stdout = await self._run_memu(
                ["retrieve", user_text],
                ctx,
                timeout=self._retrieve_timeout,
            )
            segments = json.loads(stdout).get("segments", [])[: self._search_limit]
            return self._format_segments(segments)
        except Exception as exc:  # fail-open：召回失败不影响对话
            logger.warning("[memU] retrieve failed, injecting nothing: {}", exc)
            return None

    async def on_after_turn(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        # 记忆是后台任务：本 hook 立即返回，永不阻塞下一轮。
        task = asyncio.create_task(self._memorize(user_text, assistant_text, ctx))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def flush(self) -> None:
        """等待所有后台记忆完成（测试与优雅退出用）。"""
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)

    # --------------------------------------------------------------- memorize

    async def _memorize(self, user_text: str, assistant_text: str, ctx: AgentContext) -> None:
        try:
            if not self._check_enabled():
                return
            items = await self._extract(user_text, assistant_text, ctx)
            touched = self._append_to_shadow_files(items, ctx)
            if not touched:
                return
            payload = json.dumps({"recall_files": touched}, ensure_ascii=False)
            await self._run_memu(["commit", "-"], ctx, stdin_payload=payload, timeout=self._commit_timeout)
            logger.info("[memU] committed {} recall file(s)", len(touched))
        except Exception as exc:  # 记忆失败绝不影响对话
            logger.warning("[memU] memorize skipped: {}", exc)

    async def _extract(self, user_text: str, assistant_text: str, ctx: AgentContext) -> list[dict[str, str]]:
        from lab.agent.types import OpenAIMessage

        categories = ", ".join(sorted(f.stem for f in self._recall_dir(ctx).glob("*.md"))) or "（暂无）"
        prompt = f"已有分类：{categories}\n\n对话：\n用户：{user_text}\n助手：{assistant_text}"
        llm = self._get_llm()
        chunks: list[str] = []
        async for chunk in llm.chat_completion(
            messages=[OpenAIMessage(role="user", content=prompt)],
            system=_EXTRACTION_SYSTEM,
            stream_=False,
        ):
            chunks.append(chunk)
        return parse_extraction("".join(chunks))

    def _recall_dir(self, ctx: AgentContext) -> Path:
        return self._data_dir(ctx) / "recall"

    def _append_to_shadow_files(self, items: list[dict[str, str]], ctx: AgentContext) -> list[dict[str, str]]:
        """条目按行追加进影子 markdown，返回 memu commit 的 recall_files 载荷。

        影子文件是事实源（人可读可改）；memU 拿整个文件内容按行 diff 重建 segments，
        所以这里只负责「追加不重复的行」，行格式 `name：content`（# 开头的标题行会被
        memU 跳过，不参与检索）。
        """
        recall_dir = self._recall_dir(ctx)
        touched: dict[str, Path] = {}
        for item in items[:_MAX_ITEMS_PER_TURN]:
            slug = _category_slug(item["category"])
            name = item["name"].strip()
            content = item["content"].strip()
            if not slug or not name or not content:
                logger.warning("[memU] skipped invalid item {}", item.get("name"))
                continue
            path = recall_dir / f"{slug}.md"
            recall_dir.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else f"# {slug}\n"
            line = f"{name}：{content}"
            if line not in {ln.strip() for ln in existing.splitlines()}:
                if not existing.endswith("\n"):
                    existing += "\n"
                path.write_text(existing + line + "\n", encoding="utf-8")
            touched[slug] = path
        return [
            {
                "name": slug,
                "track": "memory",
                "description": f"分类 {slug} 的长期记忆",
                "content": path.read_text(encoding="utf-8"),
            }
            for slug, path in touched.items()
        ]

    # -------------------------------------------------------------- formatting

    def _format_segments(self, segments: list[dict[str, Any]]) -> str | None:
        if not segments:
            return None
        budget_chars = self._budget_tokens * 4  # 粗略 ~4 字符/token
        lines: list[str] = []
        used = 0
        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            line = f"- {text}"
            if lines and used + len(line) > budget_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines) if lines else None
