from __future__ import annotations

import html
import ipaddress
import json
import time
import urllib.parse
import urllib.robotparser
from typing import Annotated, Any

import httpx
import pydantic
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from lab.plugin.config import PluginConfigModel
from lab.plugin.http import clamp_int, get_with_retries, make_headers
from lab.tools.base import BuiltinTool
from lab.tools.plugin import ToolPlugin
from lab.tools.types import AgentContext, ToolResult

_ROBOTS_TTL_S = 6 * 3600
_ROBOTS_CACHE: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}


class WebFetchPluginConfig(PluginConfigModel):
    user_agent: Annotated[str, Field("XnneHangLab-ToolPlugin/1.0", description="抓取网页时使用的 User-Agent 头")]
    respect_robots: Annotated[bool, Field(False, description="是否遵守目标站点的 robots.txt")]
    robots_fail_closed: Annotated[bool, Field(False, description="robots.txt 检查失败时是否默认拒绝抓取")]
    use_jina_fallback: Annotated[bool, Field(False, description="正文提取效果不佳时是否启用 Jina Reader 回退")]
    jina_api_key: Annotated[str, Field("", description="Jina Reader API Key，未配置时留空")]
    timeout_s: Annotated[float, Field(10.0, ge=1.0, le=30.0, description="网页抓取默认超时时间（秒）")]
    max_chars_default: Annotated[int, Field(8000, ge=256, le=20000, description="默认返回的最大正文字符数")]


PLUGIN_CONFIG_MODEL = WebFetchPluginConfig


class WebFetchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: AnyHttpUrl
    max_chars: int = Field(8000, ge=256, le=20000, description="Maximum characters to return.")
    timeout_s: float = Field(10.0, ge=1.0, le=30.0, description="Request timeout in seconds.")


class WebFetchResult(BaseModel):
    url: AnyHttpUrl
    status_code: int
    content_type: str | None = None
    text: str
    truncated: bool = False


def _is_probably_private_host(host: str) -> bool:
    if not host:
        return True
    normalized = host.lower().strip()
    if normalized == "localhost" or normalized.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except Exception:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _validate_public_http_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.netloc:
        raise ValueError("URL missing host")
    if _is_probably_private_host(parsed.hostname or ""):
        raise ValueError("Refuse to fetch localhost/private network URL")


async def _allowed_by_robots(
    *,
    url: str,
    user_agent: str,
    timeout_s: float,
    respect_robots: bool,
    robots_fail_closed: bool,
) -> bool:
    if not respect_robots:
        return True

    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    now = time.time()

    cached = _ROBOTS_CACHE.get(base)
    if cached and (now - cached[0]) < _ROBOTS_TTL_S:
        return cached[1].can_fetch(user_agent, url)

    robots_url = urllib.parse.urljoin(base, "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        try:
            response = await get_with_retries(client, robots_url, headers=make_headers(user_agent))
            if response.status_code >= 400:
                _ROBOTS_CACHE[base] = (now, parser)
                return not robots_fail_closed
            parser.parse(response.text.splitlines())
            _ROBOTS_CACHE[base] = (now, parser)
            return parser.can_fetch(user_agent, url)
        except Exception as exc:
            logger.warning("robots.txt check failed url={} error={} {}", url, type(exc).__name__, exc)
            return not robots_fail_closed


def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()


def _pick_main_container(soup: BeautifulSoup):
    return soup.find("article") or soup.find("main") or soup.body or soup


def _html_to_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    _clean_soup(soup)
    text = _pick_main_container(soup).get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def _extract_next_data_text(raw_html: str) -> str | None:
    soup = BeautifulSoup(raw_html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None

    try:
        data = json.loads(html.unescape(script.string))
    except Exception:
        return None

    chunks: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, str):
            stripped = value.strip()
            if len(stripped) >= 200 and (" " in stripped or "。" in stripped or "." in stripped):
                chunks.append(stripped)

    walk(data)
    if not chunks:
        return None

    out = "\n\n".join(chunks[:12])
    return out if len(out) >= 400 else None


def _looks_unusable(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 400:
        return True
    bad_markers = ["__NEXT_DATA__", "window.__ENV", "function(", "var ", "{", "};"]
    return sum(1 for marker in bad_markers if marker in stripped) >= 3


async def _fetch_via_jina(
    *,
    original_url: str,
    timeout_s: float,
    user_agent: str,
    jina_api_key: str,
) -> str | None:
    headers = make_headers(user_agent)
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"

    jina_url = f"https://r.jina.ai/{original_url}"
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        response = await get_with_retries(client, jina_url, headers=headers)
    if response.status_code >= 400:
        return None
    text = response.text.strip()
    return text or None


def _render_non_html(content_type: str | None, raw_text: str) -> str:
    if not content_type:
        return raw_text
    content_type = content_type.lower()
    if "application/json" in content_type or content_type.endswith("+json"):
        try:
            return json.dumps(json.loads(raw_text), ensure_ascii=False, indent=2)
        except Exception:
            return raw_text
    return raw_text


class _WebFetchTool(BuiltinTool):
    name = "web_fetch"
    description = "Fetch a public URL and extract readable page content."
    usage_hint = "当你已经有 URL，并需要读取网页正文、文档页面或文章内容时调用此工具。"

    def __init__(self, plugin: WebFetchPlugin) -> None:
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
                        "url": {"type": "string", "description": "Public http/https URL to fetch."},
                        "max_chars": {"type": "integer", "description": "Max characters to return (256-20000)."},
                        "timeout_s": {"type": "number", "description": "Request timeout in seconds (1-30)."},
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        try:
            parsed = WebFetchArgs.model_validate(args)
        except pydantic.ValidationError as exc:
            return ToolResult(ok=False, text="", error=str(exc))

        result = await self._plugin.fetch(
            url=str(parsed.url),
            max_chars=parsed.max_chars,
            timeout_s=parsed.timeout_s,
        )
        return ToolResult(ok=True, text=result.text, data=result.model_dump(exclude_none=True, mode="json"))


class WebFetchPlugin(ToolPlugin):
    name = "web_fetch"
    description = "Fetch a public URL and extract readable page content."
    config_model = WebFetchPluginConfig

    def __init__(
        self,
        *,
        user_agent: str = "XnneHangLab-ToolPlugin/1.0",
        respect_robots: bool = False,
        robots_fail_closed: bool = False,
        use_jina_fallback: bool = False,
        jina_api_key: str = "",
        timeout_s: float = 10.0,
        max_chars_default: int = 8000,
    ) -> None:
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.robots_fail_closed = robots_fail_closed
        self.use_jina_fallback = use_jina_fallback
        self.jina_api_key = jina_api_key
        self.timeout_s = timeout_s
        self.max_chars_default = max_chars_default
        self._tool = _WebFetchTool(self)

    def get_tools(self) -> list[BuiltinTool]:
        return [self._tool]

    async def fetch(self, *, url: str, max_chars: int, timeout_s: float) -> WebFetchResult:
        _validate_public_http_url(url)

        max_chars = clamp_int(max_chars or self.max_chars_default, 256, 20000)
        timeout_s = max(1.0, min(float(timeout_s or self.timeout_s), 30.0))

        allowed = await _allowed_by_robots(
            url=url,
            user_agent=self.user_agent,
            timeout_s=timeout_s,
            respect_robots=self.respect_robots,
            robots_fail_closed=self.robots_fail_closed,
        )
        if not allowed:
            return WebFetchResult(
                url=url,
                status_code=451,
                content_type="text/plain",
                text="Blocked by robots.txt (respect_robots=true).",
                truncated=False,
            )

        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await get_with_retries(client, url, headers=make_headers(self.user_agent))

        content_type = response.headers.get("content-type")
        raw = response.text

        if content_type and "text/html" in content_type.lower():
            text = _html_to_text(raw)
            if _looks_unusable(text):
                next_data = _extract_next_data_text(raw)
                if next_data:
                    text = next_data
            if _looks_unusable(text) and self.use_jina_fallback:
                try:
                    jina_text = await _fetch_via_jina(
                        original_url=url,
                        timeout_s=min(20.0, timeout_s + 5.0),
                        user_agent=self.user_agent,
                        jina_api_key=self.jina_api_key,
                    )
                    if jina_text and len(jina_text) >= 200:
                        text = jina_text
                except Exception as exc:
                    logger.warning("Jina fallback failed url={} error={} {}", url, type(exc).__name__, exc)
        else:
            text = _render_non_html(content_type, raw)

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return WebFetchResult(
            url=url,
            status_code=response.status_code,
            content_type=content_type,
            text=text,
            truncated=truncated,
        )
