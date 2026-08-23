# Agent 模块

`src/lab/agent/` — LLM 调用、工具循环、记忆管理。

## 目录结构

```
agent/
├── agent_factory.py          # AgentFactory：根据配置创建 AgentCore / Agent 实例
├── core.py                   # AgentCore：共享核心逻辑（tool calling / vision / prompt / storage）
├── storage.py                # ConversationStorage Protocol + 两种实现
├── types.py                  # 核心类型定义（OpenAIMessage / ContentPart / ConversationState 等）
├── stateless_llm_factory.py  # LLMFactory：创建 OpenAI Compatible LLM 实例
├── stateless_llm/
│   └── openai_compatible_llm.py  # AsyncLLM：异步流式 LLM 调用（含 stream_with_tools）
├── input_types.py            # 输入类型（BatchInput / ImageData / TextData）
├── output_types.py           # 输出类型（SentenceOutput / AudioOutput / Actions）
├── transformers.py           # 文本后处理管线（断句、表情提取、TTS 过滤）
└── agents/
    ├── agent_interface.py    # AgentInterface：抽象基类
    └── memory_agent/         # MemoryAgent：当前唯一实现
        ├── agent.py          # 编排器（orchestrator）
        ├── memory_store.py   # 内存消息列表 + 历史读写
        ├── message_factory.py # OpenAI Message 构造
        ├── prompt_builder.py  # UserPromptBlock 拼装
        ├── user_prompt_block.py # UserPromptBlock 数据结构
        ├── vision_summarizer.py # 图片摘要生成
        └── types.py           # 内部类型（ImagePayload 等）
```

## 核心概念

### AgentCore

`AgentCore`（`core.py`）是 MemoryAgent 和 `/memory/chat` 的**共享核心**，统一实现了：

### 核心类型（`types.py`）

Agent 层的公共类型与工具函数，被整个 `agent/` 及 `tools/` 广泛使用：

| 类型 / 函数 | 说明 |
|------------|------|
| `OpenAIMessage` | OpenAI messages 格式（role / content / tool_call_id / name） |
| `TextPart` / `ImagePart` / `AudioPart` / `FilePart` | 多模态 content 类型 |
| `ContentPart` | 上述类型的 Union |
| `ConversationState` | 对话状态容器（messages / refs / slots / active_task） |
| `ToolCallLike` | OpenAI tool_call Protocol（id / function.name / function.arguments） |
| `ToolTraceItem` | 工具调用 trace（server / name / args / raw_result / ok / error） |
| `ScreenShotResult` / `ImageRefResult` | 截图工具返回类型 |
| `call_with_short_retry` | 带短暂重试的异步调用包装（LLM API 调用） |
| `dump_openai_msg` | 将 `OpenAIMessage` 序列化为可读 dict（调试用） |
| `normalize_jsonlike` | 将类 JSON 对象规范化为标准 dict |

- 流式 Tool Calling（`chat_llm` 原生，多轮循环，无独立 tool model）
- Vision 预处理（`VisionSummarizer`）
- Prompt 拼装（`PromptBuilder`）
- 历史存储（`ConversationStorage`）

详见 [AgentCore 架构](./agent-core.md)。

### AgentInterface

所有 Agent 的抽象接口，定义三个核心方法：

- `chat(input_data) → AsyncIterator[BaseOutput]` — 异步流式对话
- `handle_interrupt(heard_response)` — 处理用户打断
- `set_memory_from_history(conf_uid, history_uid)` — 从历史加载记忆

### MemoryAgent

MemoryAgent 是 VTuber 链路的**编排器**，职责是将 `AgentCore` 的 token 流接入 TTS / Live2D pipeline：

| 组件 | 职责 |
|------|------|
| `AgentCore` | tool calling / vision / prompt / chat LLM / 历史存储 |
| `MemoryStore` | 维护对话 memory + 历史持久化 |
| `MessageFactory` | 构造 / 解析 OpenAI 格式消息（含多图） |
| Transformers 管线 | 断句 → 表情提取 → TTS 过滤 → 显示处理 |

MemoryAgent 本身**不做 LLM 调用**，所有生成逻辑委托给 `AgentCore.run_turn()`。

### AsyncLLM

`stateless_llm/openai_compatible_llm.py` 提供两个核心方法：

| 方法 | 用途 |
|------|------|
| `chat_completion()` | 普通流式/非流式文本生成（不带工具） |
| `stream_with_tools()` | 返回原始 `ChatCompletionChunk`，支持 text/tool_call delta 混合解析 |
| `vision_completion_once()` | 单次 vision 调用（图片摘要） |

## 数据流

一次完整对话请求的处理管线：

```
📥 BatchInput（用户输入）
    ↓
✉️ MessageFactory.extract_text_and_data_images()
    → user_text + user_images
    ↓ AgentCore.run_turn()
👁️ [has_images?] VisionSummarizer
    → vision_summaries（tool / upload 分开处理）
    ↓
📝 PromptBuilder.build()
    → UserPromptBlock（memory / diary / vision context 组合）
    ↓
🤖 chat_llm.stream_with_tools(messages, tools=schema)
    ↓
🔄 多轮循环（max 6 rounds）
    text delta    → yield str token（立刻流出）
    tool_call     → yield [🔧 name] → execute → append result → 继续
    finish=stop   → break
    ↓
💾 ConversationStorage.append_turn()
    ↓ （MemoryAgent 侧）
🔄 Transformers 管线
    sentence_divider → actions_extractor → tts_filter → display_processor
    ↓
📤 yield SentenceOutput (display_text, tts_text, actions)
```

**关键节点：**
- 👁️ 图片摘要根据模型能力决定（`chat_supports_vision=False` 时必须生成）
- 🤖 工具调用与文本生成同在一个 `chat_llm` 中，无独立 tool model
- 🔄 tool 执行期间 yield `[🔧 name]` 标签，保证用户不会看到空白等待
- 📤 输出是流式的，逐句 yield

## 模式矩阵

`AgentCore` 的行为由以下配置控制：

| 配置项 | 说明 |
|--------|------|
| `enable_tool` | 是否启用工具调用（`tools=schema` 传入 LLM） |
| `chat_supports_vision` | chat_llm 是否支持图片输入；支持时原图直接进入 chat，否则走独立视觉摘要兼容路径 |
| `require_detailed` | 仅用于非视觉 chat 的兼容路径：True 逐图并发摘要，False 一次多图摘要 |

支持视觉的 chat 模型不会预先调用 `vision_model`，因此用户随消息上传或捕获的图片会与文本一起进入同一次主模型请求。截图工具仍需先由主模型发起工具调用，但工具图片返回后会直接交给同一个视觉 chat 模型，不增加独立视觉转写步骤。

## 不变量

- **History 不写 base64**：`ConversationStorage` 只持久化纯文本内容
- **Tool 图与用户图隔离**：tool 回调图标签 `tool1`，与用户上传图 `p1/p2...` 语义分离
- **MemoryAgent 不直接调 LLM**：所有生成逻辑在 `AgentCore` 内部，MemoryAgent 只消费 token 流
