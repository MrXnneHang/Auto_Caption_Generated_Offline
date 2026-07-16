"""MemuPlugin（memu-cli 后端）：召回注入 / 后台抽取提交 / fail-open 行为。

纯单元测试：`_run_memu`（CLI 子进程）被替换为假实现，绝不真的拉起 Python 3.13 /
构建 memu-cli（那需要 Rust + embedding 端点，见 docs/guide/architecture/memu-memory.md
的 keyless smoke）。抽取 LLM 用与 wikimem 测试同款的 FakeLLM。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from lab.plugins.memu import MemuPlugin, _category_slug
from lab.tools.types import AgentContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class FakeLLM:
    """按预设文本应答的假抽取 LLM。"""

    def __init__(self, response: str) -> None:
        self.response = response

    async def chat_completion(
        self,
        messages: list[Any],
        system: str | None = None,
        *,
        stream_: bool = True,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        del messages, system, stream_, temperature
        yield self.response


def _ctx(tmp_path: Path) -> AgentContext:
    return AgentContext(workspace_root=tmp_path)


def _plugin(tmp_path: Path, llm_response: str = "[]", **kwargs: Any) -> tuple[MemuPlugin, list[dict[str, Any]]]:
    """构造插件：embedding 已配置（enabled），_run_memu 换成记录调用的假实现。"""
    del tmp_path
    plugin = MemuPlugin(embedding_base_url="http://127.0.0.1:9/v1", llm=FakeLLM(llm_response), **kwargs)  # type: ignore[arg-type]
    calls: list[dict[str, Any]] = []

    async def fake_run(args: list[str], ctx: AgentContext, *, stdin_payload: str | None = None, timeout: float) -> str:
        calls.append({"args": args, "stdin": stdin_payload, "timeout": timeout})
        if args[0] == "retrieve":
            return json.dumps(
                {
                    "segments": [
                        {"text": "喜欢海边：提到过想去海边玩", "score": 0.9},
                        {"text": "手冲咖啡：只喝手冲，不加糖", "score": 0.8},
                    ]
                }
            )
        return json.dumps({"recall_files": [], "resources": []})

    plugin._run_memu = fake_run  # type: ignore[method-assign]
    return plugin, calls


def test_before_turn_injects_segments(tmp_path: Path) -> None:
    plugin, calls = _plugin(tmp_path)

    async def _run() -> str | None:
        return await plugin.on_before_turn("想去海边玩", _ctx(tmp_path))

    injected = asyncio.run(_run())
    assert injected is not None
    assert injected.startswith("- 喜欢海边")
    assert "手冲咖啡" in injected
    assert calls[0]["args"] == ["retrieve", "想去海边玩"]


def test_before_turn_fail_open_on_cli_error(tmp_path: Path) -> None:
    plugin, _ = _plugin(tmp_path)

    async def broken(args: list[str], ctx: AgentContext, *, stdin_payload: str | None = None, timeout: float) -> str:
        raise RuntimeError("memu retrieve rc=1: build in progress")

    plugin._run_memu = broken  # type: ignore[method-assign]

    async def _run() -> str | None:
        return await plugin.on_before_turn("你好", _ctx(tmp_path))

    assert asyncio.run(_run()) is None  # 任何内部错误都不能打断对话


def test_disabled_without_embedding_config(tmp_path: Path) -> None:
    # embedding_base_url 留空 = 结构性禁用：不注入、不发起任何 CLI 调用
    plugin = MemuPlugin(llm=FakeLLM("[]"))  # type: ignore[arg-type]

    async def _run() -> str | None:
        return await plugin.on_before_turn("你好", _ctx(tmp_path))

    assert asyncio.run(_run()) is None
    assert plugin._disabled


def test_after_turn_returns_immediately(tmp_path: Path) -> None:
    plugin, _ = _plugin(tmp_path)

    async def _run() -> float:
        started = time.perf_counter()
        await plugin.on_after_turn("hi", "hello", _ctx(tmp_path))
        elapsed = time.perf_counter() - started
        await plugin.flush()
        return elapsed

    elapsed = asyncio.run(_run())
    assert elapsed < 0.2  # hook 立即返回，记忆在后台跑（永不阻塞对话）


def test_memorize_appends_shadow_file_and_commits(tmp_path: Path) -> None:
    response = '[{"category": "preferences", "name": "手冲咖啡", "content": "只喝手冲咖啡，不加糖。"}]'
    plugin, calls = _plugin(tmp_path, llm_response=response)

    async def _run() -> None:
        await plugin.on_after_turn("我只喝手冲咖啡", "记住啦", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    # 影子文件：# 标题 + 一行记忆
    shadow = tmp_path / "memu_memory" / "recall" / "preferences.md"
    assert shadow.exists()
    text = shadow.read_text(encoding="utf-8")
    assert "手冲咖啡：只喝手冲咖啡，不加糖。" in text
    # commit 载荷：整个文件内容 + memory track
    commit = next(c for c in calls if c["args"] == ["commit", "-"])
    payload = json.loads(commit["stdin"])
    (rf,) = payload["recall_files"]
    assert rf["name"] == "preferences"
    assert rf["track"] == "memory"
    assert rf["content"] == text


def test_memorize_dedupes_identical_lines(tmp_path: Path) -> None:
    response = '[{"category": "preferences", "name": "手冲咖啡", "content": "只喝手冲咖啡，不加糖。"}]'
    plugin, _ = _plugin(tmp_path, llm_response=response)

    async def _run() -> None:
        for _ in range(2):
            await plugin.on_after_turn("我只喝手冲咖啡", "记住啦", _ctx(tmp_path))
            await plugin.flush()

    asyncio.run(_run())
    text = (tmp_path / "memu_memory" / "recall" / "preferences.md").read_text(encoding="utf-8")
    assert text.count("手冲咖啡：") == 1  # 相同行不重复追加


def test_memorize_skips_invalid_items_no_commit(tmp_path: Path) -> None:
    # category 清洗后为空 → 条目丢弃；没有 touched 文件就不发 commit
    response = '[{"category": "！！！", "name": "x", "content": "y"}]'
    plugin, calls = _plugin(tmp_path, llm_response=response)

    async def _run() -> None:
        await plugin.on_after_turn("a", "b", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    assert not any(c["args"][0] == "commit" for c in calls)
    assert not (tmp_path / "memu_memory" / "recall").exists()


def test_memorize_never_raises_on_cli_failure(tmp_path: Path) -> None:
    response = '[{"category": "notes", "name": "好条目", "content": "有效内容"}]'
    plugin, _ = _plugin(tmp_path, llm_response=response)

    async def broken(args: list[str], ctx: AgentContext, *, stdin_payload: str | None = None, timeout: float) -> str:
        raise TimeoutError

    plugin._run_memu = broken  # type: ignore[method-assign]

    async def _run() -> None:
        await plugin.on_after_turn("a", "b", _ctx(tmp_path))
        await plugin.flush()  # CLI 失败也不得抛异常（影子文件仍然写了 = 事实源不丢）

    asyncio.run(_run())
    assert (tmp_path / "memu_memory" / "recall" / "notes.md").exists()


def test_format_segments_budget_and_shape(tmp_path: Path) -> None:
    plugin, _ = _plugin(tmp_path, budget_tokens=100)  # ~400 字符预算
    assert plugin._format_segments([]) is None
    out = plugin._format_segments([{"text": "第一条", "score": 0.9}, {"text": "   ", "score": 0.8}])
    assert out == "- 第一条"


def test_category_slug() -> None:
    assert _category_slug("Preferences") == "preferences"
    assert _category_slug("daily life!") == "daily-life"
    assert _category_slug("！！！") == ""
