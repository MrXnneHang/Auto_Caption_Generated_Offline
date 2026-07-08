# Conversations 模块

`src/lab/conversations/` — 对话编排、TTS 管理、中断处理。

## 目录结构

```
conversations/
├── conversation_handler.py   # 对话触发与中断处理入口
├── single_conversation.py    # 单次对话流程编排
├── conversation_utils.py     # 工具函数（表情映射等）
├── tts_manager.py            # TTS 任务管理与音频流式推送
└── types.py                  # 内部类型定义
```

## 核心概念

### 对话编排

`conversation_handler.py` 是 WebSocket 消息的业务逻辑层，处理：

- **对话触发** — `handle_conversation_trigger()`
  - `ai-speak-signal` — 用户发起对话
  - 创建对话任务，调用 `process_single_conversation()`
  
- **中断处理** — `handle_individual_interrupt()` / `handle_group_interrupt()`
  - 个体中断：用户打断 AI 说话
  - 群聊中断：群聊中某人打断

### 单次对话流程

`single_conversation.py` 编排一次完整对话：

```
1. 构造 BatchInput（文本 + 图片 + 文件）
2. 调用 agent.chat(input_data) → AsyncIterator[SentenceOutput]
3. 逐句处理：
   - 发送字幕到前端
   - 调用 TTS 生成音频
   - 推送音频 + Live2D 表情
4. 对话结束，清理资源
```

### TTS Manager

`tts_manager.py` 管理 TTS 任务队列和音频推送：

- 支持多种 TTS 后端（Genie-TTS / GSV-TTS-Lite / Qwen-TTS）
- 流式音频推送
- 音频缓存与清理
- 翻译集成（DeepLX / LLM）

## 数据流

```
WebSocket 消息
    ↓
conversation_handler.py（路由）
    ↓
single_conversation.py（编排）
    ↓
agent.chat() → yield SentenceOutput
    ↓
tts_manager.py（TTS 生成 + 推送）
    ↓
WebSocket 推送到前端
```

## 与其他模块的关系

- **websocket_handler.py** 调用 `conversation_handler` 处理业务逻辑
- **agent/** 提供 LLM 推理能力
- **api/clients/** 调用 TTS / 翻译服务
- **service_context.py** 提供 Agent 和配置上下文
