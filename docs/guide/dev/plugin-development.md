# 插件开发指南

> 如何为 XnneHangLab 编写 `tool`、`skill` 和 `hook` 插件。

## 前置知识

- 了解 [Plugin 系统架构](../architecture/plugin-system)
- 了解 `BuiltinTool` 基类（`src/lab/tools/base.py`）
- 了解 `ToolPlugin` 基类（`src/lab/tools/plugin.py`）
- 了解 `HookPlugin` 基类（`src/lab/plugin/hook.py`）
- 了解 `HookManager`（`src/lab/agent/hook_manager.py`）

---

## 一个最小的 tool plugin

以「返回当前时间」为例，新建 `src/lab/plugins/get_time/`：

### 1. `plugin.toml`

```toml
[plugin]
id = "get_time"
name = "Get Time"
description = "获取当前日期时间"
type = "tool"

[config]
timezone = "Asia/Shanghai"   # 默认时区，可被 Profile 覆盖
```

### 2. `__init__.py`

```python
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from lab.tools.base import BuiltinTool
from lab.tools.plugin import ToolPlugin
from lab.tools.types import AgentContext, ToolResult


class _GetTimeTool(BuiltinTool):
    name = "get_time"
    description = "获取当前日期和时间。"
    usage_hint = "当用户询问当前时间、日期时调用此工具。"

    def __init__(self, plugin: GetTimePlugin) -> None:
        self._plugin = plugin

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        tz = ZoneInfo(self._plugin.timezone)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        return ToolResult(ok=True, text=now)


class GetTimePlugin(ToolPlugin):
    name = "get_time"
    description = "获取当前日期时间"

    def __init__(self, *, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = timezone
        self._tool = _GetTimeTool(self)

    def get_tools(self) -> list[BuiltinTool]:
        return [self._tool]
```

### 3. 在 Profile 里启用

```toml
# profiles/songyin.toml
[plugins]
enabled = ["get_time", "web_fetch"]

[plugins.get_time]
timezone = "UTC"    # 覆盖默认时区
```

完成。PluginLoader 会自动发现并加载。

---

## BuiltinTool 接口

```python
class BuiltinTool(ABC):
    name: str         # 工具名，全局唯一，LLM 调用时用这个
    description: str  # 工具描述
    usage_hint: str   # 使用时机提示（注入 system prompt）

    @abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """返回 OpenAI function calling schema。"""

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        """执行工具，返回结果。"""
```

`ToolResult` 字段：

```python
@dataclass
class ToolResult:
    ok: bool            # 是否成功
    text: str           # 返回给 LLM 的文本内容
    error: str = ""     # 失败时的错误描述
    data: Any = None    # 可选的结构化数据
```

---

## ToolPlugin 接口

```python
class ToolPlugin(ABC):
    name: str         # 插件名
    description: str  # 插件描述

    @abstractmethod
    def get_tools(self) -> list[BuiltinTool]:
        """返回此插件提供的所有工具。"""

    async def on_register(self, ctx: AgentContext) -> bool:
        """
        注册前的钩子（可选）。
        返回 False 跳过注册（例如：配置缺失时静默跳过）。
        """
        return True
```

`on_register` 适合做「条件注册」，比如 `web_search_searxng` 在 `searxng_url` 为空时返回 `False` 跳过注册：

```python
async def on_register(self, ctx: AgentContext) -> bool:
    if not self.searxng_url.strip():
        logger.info("searxng_url 未配置，跳过注册")
        return False
    return True
```

---

## 配置注入机制

`PluginLoader` 用 `inspect.signature` 自动从 `plugin.toml [config]` 过滤出构造函数接受的参数：

```python
# plugin.toml
[config]
timeout_s = 10.0
respect_robots = true   # 如果构造函数没有这个参数，自动忽略
max_chars = 8000

# 构造函数
def __init__(self, *, timeout_s: float = 10.0, max_chars: int = 8000) -> None:
    ...
# respect_robots 不在签名里 → 自动过滤，不会报错
```

配置优先级：`plugin.toml [config]` < `Profile [plugins.<id>]` 覆盖值。

---

## 插件隔离规则

**插件之间不能互相 import。** 如果多个插件需要共享工具：

```python
# ❌ 禁止
from lab.plugins.web_fetch import get_with_retries

# ✅ 放到框架层
from lab.plugin.http import get_with_retries   # 已有
from lab.plugin.search_types import WebSearchResult  # 已有
```

新的共享工具请提 PR，加到 `src/lab/plugin/` 下。

---

## 调试技巧

```bash
# 验证 plugin 能被正确加载
python -c "
import asyncio
from pathlib import Path
from lab.plugin.loader import PluginLoader

async def test():
    loader = PluginLoader(Path('.'))
    tools, skills, hooks = await loader.load_many(['get_time'])
    print('tools:', tools)
    print('skills:', skills)
    print('hooks:', hooks)

asyncio.run(test())
"

# 跑 lint
uv run ruff check src/lab/plugins/get_time/
uv run ty check src/lab/plugins/get_time/
```

---

## skill plugin

`type = "skill"` 的插件由 `PluginLoader` 解析为 `SkillDescriptor`，不实例化 Python 类。

添加步骤：

1. 新建 `src/lab/plugins/<id>/` 目录
2. 写 `plugin.toml`，设置 `type = "skill"`，填好 `description` 和 `[type_config]`
3. 把技能内容写进 `skill.md`
4. Profile 的 `[plugins].enabled` 加上这个 id

内置的 `src/lab/plugins/diary/` 是一个完整的 skill plugin 示例，可以直接参考。

`inline` 字段决定注入方式：

| `inline` | 行为 |
|---|---|
| `true` | 启动时把 skill 内容直接展开到 system prompt（适合短小、始终生效的规范） |
| `false` | 只注入描述 + 文件路径，模型按需读取（适合长篇偶发指引） |

---

## hook plugin

`type = "hook"` 的插件继承 `HookPlugin`，由 `HookManager` 在每轮 `run_turn` 前调用 `on_before_turn(user_text, ctx)`。

返回字符串时注入当轮 `memory_context`，返回 `None` 表示本轮跳过。

### 1. `plugin.toml`

```toml
[plugin]
id = "my_hook"
name = "My Hook"
type = "hook"
description = "在每轮对话前做某件事"

[config]
base_url = "http://localhost:8080"
timeout_s = 5.0

[type_config]
entry = "MyHookPlugin"
requires_package = "my_service"   # 可选，不填则不校验 package 开关
```

### 2. `__init__.py`

```python
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from lab.plugin.hook import HookPlugin

if TYPE_CHECKING:
    from lab.tools.types import AgentContext


class MyHookPlugin(HookPlugin):
    _requires_package = "my_service"   # 对应 [package] my_service = true

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    async def on_before_turn(self, user_text: str, ctx: AgentContext) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                resp = await client.post(
                    f"{self._base_url}/search",
                    json={"query": user_text},
                )
                resp.raise_for_status()
                # 返回注入 memory_context 的纯文本
                return resp.json().get("result") or None
        except Exception:
            return None  # 降级：服务不可用时静默跳过，不影响主流程
```

**几个要点：**
- `on_before_turn()` 只负责准备本轮上下文，不直接干预主流程控制
- 服务不可用、超时、格式异常时**必须静默返回 `None`**，做好降级保护
- 返回值应是适合直接注入 `memory_context` 的纯文本

### 3. `_requires_package` 说明

`_requires_package` 与 `agent_factory` 的 package 开关校验联动：

- 插件类声明 `_requires_package = "my_service"` → 启动时检查 `[package] my_service = true`
- 如果 package 未启用，`agent_factory` 在启动阶段抛出清晰的 `ValueError`，不等到对话时才失败

### 4. 在 Profile 里启用

```toml
[plugins]
enabled = ["web_fetch", "memory"]

[plugins.memory]
user_id = "xnne"
agent_id = "congyin"
search_limit = 10
```

hook plugin 的启用和配置覆盖方式与 tool plugin 完全相同。

### 5. 内置示例

内置的 `MemoryPlugin`（`src/lab/plugins/memory/`）是当前推荐参考的 hook plugin 完整示例。
