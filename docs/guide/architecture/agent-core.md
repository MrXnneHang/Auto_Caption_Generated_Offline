# AgentCore 架构

`AgentCore` 是 `MemoryAgent`（VTuber 链路）和 `/memory/chat`（HTTP 端点）的共享核心，统一管理以下逻辑：

- 统一流式 Tool Calling（`chat_llm` 原生驱动，无独立 tool model）
- Vision summary（`VisionSummarizer`，`vision_llm` 驱动）
- Prompt 拼装（`PromptBuilder` + `UserPromptBlock`）
- Memory / Diary context 注入
- 流式对话生成与历史存储（`ConversationStorage`）

两端的差异只在**输出处理**和**历史存储实现**，通过 `ConversationStorage` Protocol 抽象插拔。

## 架构概览

```
调用方
  ├── MemoryAgent          # VTuber 链路，流式 → TTS / Live2D
  └── /memory/chat 端点    # HTTP 端点，收集完成 → JSON

       ↓ run_turn()

┌─────────────────────────────────────────────────────┐
│                     AgentCore                       │
│                                                     │
│  vision 预处理 ──────────────────────────┐          │
│  prompt 拼装（memory / diary / vision）  │          │
│                                          ↓          │
│  ┌──────────────────────────────────────────────┐  │
│  │  chat_llm.stream_with_tools(tools=schema)    │  │
│  │                                              │  │
│  │  loop (max 6 rounds):                        │  │
│  │   text delta  → yield str token              │  │
│  │   tool_call   → yield [🔧 name]              │  │
│  │              → execute via ToolManager       │  │
│  │              → append tool result            │  │
│  │              → continue stream               │  │
│  │   stop        → break                        │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ConversationStorage.append_turn()                  │
│  HookManager.after_turn()                           │
└─────────────────────────────────────────────────────┘
```

## 统一流式 Tool Calling

PR #295 / #296 移除了独立的 `tool_model`，将工具调用与对话生成合并到单个 `chat_llm` 中。

### 核心设计

OpenAI streaming API 中，一个 response 的 `delta` 要么携带 `content`（文本 token），要么携带 `tool_calls`（工具调用片段），二者互斥。`finish_reason` 区分两种终态：

- `stop` — 模型正常结束，没有工具调用
- `tool_calls` — 模型请求调用工具，需要执行后继续

`AgentCore.run_turn()` 实现了多轮循环来处理这个协议：

```python
for round in range(max_rounds):  # 最多 6 轮
    async for chunk in chat_llm.stream_with_tools(messages, tools=schema):
        if delta.content:
            yield delta.content          # 文本立刻流出
        if delta.tool_calls:
            accumulate(tool_calls_buf)   # 收集工具调用片段
    
    if finish_reason == "tool_calls":
        for tc in tool_calls:
            yield f"[🔧 {tc.name}]\n"   # 用户立刻看到工具状态
        results = await gather(*execute_tools(...))
        messages += tool_results
        # 继续下一轮，让模型基于结果继续生成
    else:
        break
```

### 工具状态标签

每次 tool call 执行前，`run_turn()` 会 yield 一个 `[🔧 tool_name]` 标签，使用户在工具执行期间（而非执行完成后）立刻看到反馈。

- **VTuber（MemoryAgent）**：TTS pipeline 过滤该标签，不读出；前端可用于显示工具调用动画
- **AIChat（/memory/chat）**：混入完整回复，前端可选择渲染为灰色状态行或忽略

### 移除的组件

| 移除 | 替代 |
|------|------|
| `AgentToolLoop` | `chat_llm.stream_with_tools()` |
| `AgentToolLoopRunner` | `AgentCore.run_turn()` 内置循环 |
| `tool_completion()` | 删除，无替代 |
| `tool_model` 配置 | 无，统一使用 `chat_model` |
| `tool_system_prompt` | 无，工具 schema 直接通过 API `tools=` 参数传入 |

## ConversationStorage

`ConversationStorage` 是 `AgentCore` 与历史存储之间的 Protocol，使两个调用方复用同一套 `run_turn()` 逻辑。

```
ConversationStorage (Protocol)
├── load() → list[OpenAIMessage]      # 读取对话历史
└── append_turn(user_block, response) # 写回一轮对话

实现：
├── MemoryStoreAdapter      ← MemoryAgent / VTuber 使用
│     内部：MemoryStore（内存列表 + 磁盘持久化）
└── ConversationStoreAdapter ← /memory/chat 使用
      内部：ConversationStore（按日期 JSON 文件）
```

## AgentCore 初始化参数

| 参数 | 说明 |
|------|------|
| `chat_llm` | 用于对话生成和工具调用的 LLM 实例 |
| `vision_llm` | 可选，用于图片摘要的视觉模型 |
| `tool_manager` | 可选，工具注册表；为 None 时禁用工具调用 |
| `agent_context` | 工具执行上下文（workspace_root 等） |
| `context_injector` | Profile 中的 context 注入配置 |
| `storage` | ConversationStorage 实现 |
| `chat_system_prompt` | 完整系统提示词（含 persona / format / skills / tools） |
| `enable_tool` | 是否启用工具调用 |
| `chat_supports_vision` | chat_llm 是否原生支持图片输入 |

## 调用方对比

| | MemoryAgent | /memory/chat |
|---|---|---|
| Storage | `MemoryStoreAdapter` | `ConversationStoreAdapter` |
| Profile | `memory_agent_profile`（baoqiao.toml）| `memory_chat_profile`（congyin.toml）|
| `write_back` | False（由 MemoryAgent 统一写回）| True |
| 输出方式 | token 流 → 断句 → TTS / Live2D | token 流收集完 → JSONResponse |
| tool 标签 | TTS 过滤，不读出 | 混入回复，前端处理 |

两条链路共用同一套 AgentCore 逻辑，差异完全由 Profile 封装。长期记忆由 `wikimem` 插件承担：`[plugins.wikimem] memory_dir` 决定记忆目录（默认 workspace 下 `memory/`，各 profile 共享；需要隔离时给不同 profile 配不同目录）。
