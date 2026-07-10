"""WikimemPlugin：召回注入 / 后台抽取 / fail-open 行为。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from wikimem import MemoryStore

from lab.plugins.wikimem import WikimemPlugin, parse_extraction
from lab.tools.types import AgentContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class FakeLLM:
    """记录调用参数、按预设文本应答的假 LLM。"""

    def __init__(self, response: str, delay: float = 0.0) -> None:
        self.response = response
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(
        self,
        messages: list[Any],
        system: str | None = None,
        *,
        stream_: bool = True,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "system": system, "stream": stream_})
        del temperature
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.response


def _ctx(tmp_path: Path) -> AgentContext:
    return AgentContext(workspace_root=tmp_path)


def _seed(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path / "memory")
    store.add(
        "preferences",
        "likes-the-sea",
        "喜欢海边，提到过想去海边玩。[[daily_life:海边旅行计划]]",
        owner="xnne",
    )
    store.add("daily_life", "海边旅行计划", "计划夏天去海边旅行，看日出。", owner="xnne")
    return store


def test_before_turn_injects_seeded_memory(tmp_path: Path) -> None:
    _seed(tmp_path)
    plugin = WikimemPlugin(llm=FakeLLM("[]"))  # type: ignore[arg-type]

    async def _run() -> str | None:
        return await plugin.on_before_turn("想去海边玩", _ctx(tmp_path))

    injected = asyncio.run(_run())
    assert injected is not None
    assert "喜欢海边" in injected
    assert "[preferences:likes-the-sea]" in injected
    # 一跳 wiki-link 展开的目标也应注入
    assert "海边旅行计划" in injected


def test_before_turn_fail_open(tmp_path: Path) -> None:
    plugin = WikimemPlugin(memory_dir="\0invalid", llm=FakeLLM("[]"))  # type: ignore[arg-type]

    async def _run() -> str | None:
        return await plugin.on_before_turn("你好", _ctx(tmp_path))

    assert asyncio.run(_run()) is None  # 任何内部错误都不能打断对话


def test_after_turn_memorizes_in_background(tmp_path: Path) -> None:
    response = (
        "好的，以下是抽取结果：\n```json\n"
        '[{"category": "preferences", "name": "手冲咖啡", '
        '"content": "只喝手冲咖啡，不加糖。"}]\n```'
    )
    llm = FakeLLM(response)
    plugin = WikimemPlugin(user_id="tester", llm=llm)  # type: ignore[arg-type]

    async def _run() -> None:
        await plugin.on_after_turn("我只喝手冲咖啡", "记住啦", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    store = MemoryStore(tmp_path / "memory")
    item = store.get("preferences", "手冲咖啡")
    assert item is not None
    assert item.owner == "tester"
    assert llm.calls and llm.calls[0]["stream"] is False


def test_after_turn_returns_before_llm_finishes(tmp_path: Path) -> None:
    llm = FakeLLM("[]", delay=0.5)
    plugin = WikimemPlugin(llm=llm)  # type: ignore[arg-type]

    async def _run() -> float:
        started = time.perf_counter()
        await plugin.on_after_turn("hi", "hello", _ctx(tmp_path))
        elapsed = time.perf_counter() - started
        await plugin.flush()
        return elapsed

    elapsed = asyncio.run(_run())
    assert elapsed < 0.2  # hook 立即返回，抽取在后台跑（永不阻塞对话）


def test_malformed_llm_output_is_skipped(tmp_path: Path) -> None:
    plugin = WikimemPlugin(llm=FakeLLM("完全不是 JSON 的回答"))  # type: ignore[arg-type]

    async def _run() -> None:
        await plugin.on_after_turn("a", "b", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    assert MemoryStore(tmp_path / "memory").items() == []


def test_invalid_item_skipped_valid_kept(tmp_path: Path) -> None:
    response = (
        '[{"category": "Bad Slug!", "name": "x", "content": "y"},'
        ' {"category": "notes", "name": "好条目", "content": "有效内容"}]'
    )
    plugin = WikimemPlugin(llm=FakeLLM(response))  # type: ignore[arg-type]

    async def _run() -> None:
        await plugin.on_after_turn("a", "b", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    items = MemoryStore(tmp_path / "memory").items()
    assert [item.name for item in items] == ["好条目"]


def test_prompt_carries_categories_and_related_items(tmp_path: Path) -> None:
    _seed(tmp_path)
    llm = FakeLLM("[]")
    plugin = WikimemPlugin(llm=llm)  # type: ignore[arg-type]

    async def _run() -> None:
        await plugin.on_before_turn("想去海边玩", _ctx(tmp_path))
        await plugin.on_after_turn("想去海边玩", "好呀", _ctx(tmp_path))
        await plugin.flush()

    asyncio.run(_run())
    prompt = str(llm.calls[0]["messages"][0].content)
    assert "preferences" in prompt  # 已有分类
    assert "preferences:likes-the-sea" in prompt  # 本轮相关条目（链接目标候选）


def test_parse_extraction_tolerates_noise() -> None:
    fenced = '前言\n```json\n[{"category": "a", "name": "b", "content": "c"}]\n```\n后记'
    assert parse_extraction(fenced) == [{"category": "a", "name": "b", "content": "c"}]
    assert parse_extraction("[]") == []
    assert parse_extraction("no json here") == []
    assert parse_extraction('{"not": "a list"}') == []
    assert parse_extraction('[1, "str", {"category": "a"}]') == []
