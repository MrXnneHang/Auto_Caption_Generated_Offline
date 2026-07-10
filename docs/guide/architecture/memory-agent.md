# MemoryAgent 架构说明

本文描述 `MemoryAgent` 的模块分层、数据流与关键决策，面向工程维护与架构理解。

## 定位与职责

`MemoryAgent` 是 VTuber 链路的**编排器**，职责是将 `AgentCore` 的 token 流接入 TTS / Live2D pipeline。

它**不做**：
- LLM 调用（委托给 AgentCore）
- 工具调用（委托给 AgentCore + ToolManager）
- Prompt 拼装（委托给 AgentCore → PromptBuilder）
- Vision 摘要（委托给 AgentCore → VisionSummarizer）

它**只做**：
- 从 `AgentCore.run_turn()` 消费 token 流
- 断句 → 表情/动作提取 → TTS 过滤 → 显示处理
- 维护 `MemoryStore`（对话消息列表 + 本地历史持久化）

> 这里的 `MemoryStore` 只管对话消息列表与本地历史，不负责长期记忆的读写。长期记忆由 `wikimem` 插件（hook 插件）承担，两者职责不同。

## 模块分层

```
MemoryAgent (agent.py)                ← 编排器
├── AgentCore (core.py)               ← 共享核心（tool / vision / prompt / LLM）
│   ├── AsyncLLM.stream_with_tools()  ← 统一流式 tool calling
│   ├── VisionSummarizer              ← 图片摘要
│   ├── PromptBuilder                 ← UserPromptBlock 拼装
│   └── ConversationStorage           ← MemoryStoreAdapter（写回由 MemoryAgent 接管）
├── MemoryStore (memory_store.py)     ← memory / history / interrupt
├── MessageFactory (message_factory.py) ← 消息解析与构造
└── Transformers 管线 (transformers.py)
    sentence_divider → actions_extractor → tts_filter → display_processor
```

::: tip AgentCore.write_back = False
`MemoryAgent` 初始化时将 `core.write_back` 设为 `False`，由 MemoryAgent 自身统一负责写回 `MemoryStore`。这样 assistant message 的写入时机与 TTS 流程对齐，避免双写。
:::

## 数据流

```
📥 BatchInput（用户输入：文本 + 可选图片）
    ↓
✉️ MessageFactory.build_user_message_from_batch()
    ↓
💬 AgentCore.run_turn(user_text, user_images)
    ─────────────────────────────────────────
    │  [vision 预处理] VisionSummarizer
    │  [prompt 拼装]   PromptBuilder
    │
    │  chat_llm.stream_with_tools(messages, tools=schema)
    │  loop:
    │    text delta → yield str
    │    tool_call  → yield [🔧 name] → execute → continue
    │    stop       → break
    ─────────────────────────────────────────
    ↓ yield str tokens
🔄 Transformers 管线
    sentence_divider      # 按标点断句
      → actions_extractor # 提取 [emotion]/[sound] 等动作标签
      → tts_filter        # 过滤 [think]/[🔧 ...] 等不朗读内容
      → display_processor # 处理显示文本（think 折叠等）
    ↓
📤 yield SentenceOutput
    ├── display_text  # 字幕 / 弹幕
    ├── tts_text      # 送 TTS 朗读的文本（已过滤标签）
    └── actions       # Live2D 动作 / 表情 / 音效
    ↓
💾 MemoryStore.add_message()  # 写回 user + assistant message
```

## 关键设计决策

### 工具状态标签不朗读

`AgentCore` 在执行工具前 yield `[🔧 tool_name]` 标签。`tts_filter` 依据 `ignore_brackets` 配置过滤掉方括号内容（或通过 tag 机制识别），保证 TTS 不读出工具状态，但字幕仍可展示。

### Vision 决策

`chat_supports_vision`（来自 `lab.toml` 的 `[agent.chat_model]`）决定图片处理方式：

| chat_supports_vision | require_detailed | 行为 |
|---|---|---|
| False | any | 必须生成 vision 摘要，纯文本喂 chat |
| True | False | 图片直接喂 chat，不生成摘要 |
| True | True | 图片喂 chat + 同步生成逐图摘要（双保险） |

### History 不存 base64

`MemoryStore` 写回时只存文本内容，不保留图片 base64，避免 memory 文件膨胀。

### Tool 图与用户图隔离

- 工具回调图：标签 `tool1`，来源 `source="tool"`
- 用户上传图：标签 `p1`/`p2`/...，来源 `source="upload"`

两类图片在 vision 摘要和 prompt 注入时分开处理，不混用标签。

## 扩展点

- **多工具截图**：在 ToolManager 侧收集多张 tool 图，给出 `tool1/tool2...` 标签（目前默认单张）
- **支持 http(s) 图片**：在 `MessageFactory.extract_text_and_data_images` 扩展
- **自定义断句**：`segment_method` 支持 `pysbd` / 自定义标点规则
- **中断方式**：`interrupt_method=system`（注入 system message）或 `user`（注入 user message）

## 记忆读写

长期记忆的读写不在 `MemoryAgent` 里，而在 `wikimem` 插件（hook 插件）里：

- **读**：`on_before_turn` → wikimem `MemoryIndex.retrieve()`（内存 BM25 + 可选 embedding 融合 + 一跳 wiki-link 展开），结果注入本轮 `memory_context`
- **写**：`on_after_turn` → 后台任务里单次抽取 LLM 调用 → 写入 workspace 下的 markdown 分类文件

记忆目录来自 Profile 的 `[plugins.wikimem] memory_dir`（默认 `memory/`）。各 profile 默认共享同一目录；需要各写各的时配不同目录即可。
