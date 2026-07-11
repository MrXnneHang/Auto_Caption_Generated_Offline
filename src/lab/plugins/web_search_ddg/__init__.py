from __future__ import annotations

import html
import json
import urllib.parse
from typing import Annotated, Any

import httpx
import pydantic
from bs4 import BeautifulSoup
from pydantic import Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.http import clamp_int, get_with_retries, make_headers
from lab.plugin.search_types import WebSearchArgs, WebSearchResult, WebSearchResultItem
from lab.tools.base import BuiltinTool
from lab.tools.plugin import ToolPlugin
from lab.tools.types import AgentContext, ToolResult


class WebSearchDuckDuckGoPluginConfig(PluginConfigModel):
    user_agent: Annotated[
        str, Field("XnneHangLab-ToolPlugin/1.0", description="请求 DuckDuckGo 时使用的 User-Agent 头")
    ]
    timeout_s: Annotated[float, Field(10.0, ge=1.0, le=60.0, description="DuckDuckGo 搜索请求超时时间（秒）")]


PLUGIN_CONFIG_MODEL = WebSearchDuckDuckGoPluginConfig


def _is_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _dedup_keep_order(items: list[WebSearchResultItem]) -> list[WebSearchResultItem]:
    seen: set[str] = set()
    out: list[WebSearchResultItem] = []
    for item in items:
        url = str(item.url)
        if url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def _decode_ddg_redirect(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        if "duckduckgo.com/l/" in url or parsed.path.startswith("/l/"):
            query = urllib.parse.parse_qs(parsed.query)
            uddg = query.get("uddg", [None])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
    except Exception:
        return url
    return url


def _parse_ddg_html_results(html_text: str, max_results: int) -> list[WebSearchResultItem]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[WebSearchResultItem] = []

    for anchor in soup.select("a.result__a"):
        title = anchor.get_text(" ", strip=True) or "No title"
        href: str = html.unescape(str(anchor.get("href") or ""))
        href = _decode_ddg_redirect(href)
        if href.startswith("//"):
            href = "https:" + href
        if not _is_http_url(href):
            continue

        snippet = None
        block = anchor.find_parent(class_="result")
        if block:
            snippet_node = block.select_one(".result__snippet")
            if snippet_node:
                snippet = snippet_node.get_text(" ", strip=True) or None

        try:
            items.append(WebSearchResultItem(title=title, url=href, snippet=snippet))
        except pydantic.ValidationError:
            continue

        if len(items) >= max_results:
            break

    return _dedup_keep_order(items)


class _WebSearchTool(BuiltinTool):
    name = "web_search"
    description = "Search the web and return a small list of results with title, URL and snippet."
    usage_hint = "当需要快速查找网页结果、文档链接或候选来源时调用此工具。"

    def __init__(self, plugin: WebSearchDuckDuckGoPlugin) -> None:
        self._plugin = plugin

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keywords or natural language query."},
                        "max_results": {"type": "integer", "description": "Number of results to return (1-10)."},
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        try:
            parsed = WebSearchArgs.model_validate(args)
        except pydantic.ValidationError as exc:
            return ToolResult(ok=False, text="", error=str(exc))

        result = await self._plugin.search(query=parsed.query, max_results=parsed.max_results)
        content = json.dumps(
            [item.model_dump(exclude_none=True, mode="json") for item in result.results],
            ensure_ascii=False,
        )
        return ToolResult(ok=True, text=content, data=result.model_dump(exclude_none=True, mode="json"))


class WebSearchDuckDuckGoPlugin(ToolPlugin):
    name = "web_search_ddg"
    description = "Search the web using DuckDuckGo HTML results."
    config_model = WebSearchDuckDuckGoPluginConfig

    def __init__(self, *, user_agent: str = "XnneHangLab-ToolPlugin/1.0", timeout_s: float = 10.0) -> None:
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self._tool = _WebSearchTool(self)

    def get_tools(self) -> list[BuiltinTool]:
        return [self._tool]

    async def search(self, *, query: str, max_results: int) -> WebSearchResult:
        max_results = clamp_int(max_results, 1, 10)
        async with httpx.AsyncClient(timeout=float(self.timeout_s), follow_redirects=True) as client:
            response = await get_with_retries(
                client,
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers=make_headers(self.user_agent),
            )
        response.raise_for_status()
        return WebSearchResult(query=query, results=_parse_ddg_html_results(response.text, max_results))
