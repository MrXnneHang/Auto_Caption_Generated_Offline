# 🚀 FastAPI 接口说明

本项目后端基于 **FastAPI**，统一提供 ASR、TTS、翻译、WebSocket 对话以及 Memory Bench 等服务。

> 🧭 默认地址：`http://127.0.0.1:12393`（端口由 `lab.toml` 的 `[server] port` 配置）
>
> 🔎 自动文档：Swagger `/docs` ｜ ReDoc `/redoc`
>
> ✅ 测试命令以 justfile 为准（`just test-*`）

## 启动服务

```bash
just server
```

等价于 `uv run run_server.py`。可通过 `--port` 覆盖端口：

```bash
uv run run_server.py --port 8080
```

---

## 路由总览

各路由模块按 `lab.toml` 中的 `[package]` 开关**条件加载**，未启用的模块不会注册路由。

```text
/
├─ /docs                              Swagger UI
├─ /redoc                             ReDoc
│
├─ /asr                               🎙️ 语音识别
│  ├─ /sherpa                          Sherpa-ONNX Paraformer（需要 sherpa_asr=true）
│  │  ├─ POST /transcribe             语音识别
│  │  └─ POST /vad                    VAD（语音活动检测）
│  ├─ /qwen-asr                        Qwen3-ASR OpenVINO（需要 qwen_asr=true）
│  │  ├─ POST /0.6B/transcribe        0.6B 模型识别
│  │  └─ POST /1.7B/transcribe        1.7B 模型识别
│  ├─ POST /reload                    重载所有已启用的 ASR 引擎
│  └─ POST /sherpa/reload             仅重载 Sherpa-ONNX 引擎
│
├─ /tts                               🗣️ 语音合成
│  ├─ /genie-tts                      Genie-TTS（需要 genie_tts=true）
│  │  ├─ POST /generate              合成（JSON → 直接返回 WAV）
│  │  ├─ GET /health                 健康检查
│  │  └─ GET /status                 当前加载状态
│  ├─ /gsv-lite                       GSV-Lite（需要 gsv_lite=true）
│  │  ├─ POST /generate              合成（JSON → 直接返回 WAV）
│  │  ├─ GET /health                 健康检查
│  │  └─ GET /status                 当前加载状态
│  └─ /qwen-tts                        Qwen-TTS（需要 qwen_tts=true）
│     ├─ POST /generate               非流式合成（返回 WAV）
│     ├─ POST /generate/stream        流式合成（SSE 事件流）
│     └─ GET /health                  健康检查
│
├─ /translate                         🌍 翻译
│  └─ /deeplx
│     ├─ POST /                       DeepLX 翻译
│     └─ GET /health                  健康检查
│
├─ /client-ws                         🔌 WebSocket（Open-LLM-VTuber 对话）
│
├─ /memory                            🧠 记忆聊天（需要 agent.memory_chat_profile）
│  └─ POST /chat                      Memory Chat（带 session 管理 + 工具调用）
│
├─ /web-tool                          🛠️ 静态 Web 工具页
├─ /live2d-models/*                   📦 Live2D 模型静态文件
├─ /bg/*                              🖼️ 背景图片静态文件
└─ /avatars/*                         👤 头像静态文件
```

---

## 🎙️ ASR（语音识别）

所有 ASR 端点接收 `multipart/form-data`，字段名 `file`，返回 JSON。

---

### Sherpa-ONNX Paraformer

**前缀**：`/asr/sherpa` — **源码**：`src/lab/api/routes/asr_sherpa.py`

需要 `lab.toml` 中 `[package] sherpa_asr = true`。

#### POST `/asr/sherpa/transcribe`

使用 Sherpa-ONNX Paraformer 进行语音识别。

```bash
just test-asr
# curl -X POST "http://localhost:12393/asr/sherpa/transcribe" -F "file=@./voices/example3.opus"
```

**响应示例**：
```json
{
  "key": "example3",
  "processing_time": 0.21,
  "text": "那年长街春意正浓策马同游",
  "code": "200",
  "message": "ASR processed successfully"
}
```

#### POST `/asr/sherpa/vad`

语音活动检测（Voice Activity Detection），返回语音片段的起止时间。

```bash
just test-vad
```

**响应示例**：
```json
{
  "segments": [[0.5, 3.2], [4.1, 7.8]],
  "code": "200",
  "message": "VAD processed successfully"
}
```

---

### Qwen3-ASR（OpenVINO INT8）

**前缀**：`/asr/qwen-asr` — **源码**：`src/lab/api/routes/asr_qwen.py`

需要 `lab.toml` 中 `[package] qwen_asr = true`。基于 OpenVINO INT8 量化，支持 0.6B 和 1.7B 两种规格。

#### POST `/asr/qwen-asr/0.6B/transcribe`

使用 Qwen3-ASR 0.6B 模型识别。

```bash
curl -X POST "http://localhost:12393/asr/qwen-asr/0.6B/transcribe" -F "file=@./voices/example3.opus"
```

#### POST `/asr/qwen-asr/1.7B/transcribe`

使用 Qwen3-ASR 1.7B 模型识别，精度更高。

```bash
curl -X POST "http://localhost:12393/asr/qwen-asr/1.7B/transcribe" -F "file=@./voices/example3.opus"
```

**响应示例**（两个端点格式相同）：
```json
{
  "key": "example3",
  "processing_time": 5.2,
  "text": "那年长街春意正浓策马同游",
  "code": "200",
  "message": "Qwen3-ASR processed successfully"
}
```

> **性能提示**：0.6B 和 1.7B 需分别在 `lab.toml` 的 `[asr.qwen_asr] preload_models` 中声明后才会预加载。首次请求未预加载的模型会触发即时加载，速度较慢。

---

### ASR 重载

**源码**：`src/lab/api/routes/asr_reload.py`

#### POST `/asr/reload`

重载所有当前启用的 ASR 引擎（`sherpa_asr` 和 `qwen_asr` 各自触发）。

**响应示例**：
```json
{
  "code": 200,
  "message": "ASR model(s) reloaded successfully!"
}
```

#### POST `/asr/sherpa/reload`

仅重载 Sherpa-ONNX 引擎（热更新，无需重启服务）。

---

## 🗣️ TTS（语音合成）

### Genie-TTS

**前缀**：`/tts/genie-tts` — **源码**：`src/lab/api/routes/genie_tts.py`

#### POST `/tts/genie-tts/generate`

提交 JSON，直接返回 WAV 音频。

```bash
curl -X POST "http://127.0.0.1:12393/tts/genie-tts/generate" \
  -H "Content-Type: application/json" \
  -d '{ \
    "text": "你好，这是 Genie-TTS 接口测试。", \
    "ref_audio_path": "models/genie-tts/baoqiao/emotions/neutral.wav", \
    "ref_text": "你好，这是参考音频文本。" \
  }' \
  -o genie_tts.wav
```

**请求体**：
```json
{
  "text": "合成文本",
  "ref_audio_path": "models/genie-tts/<character>/emotions/neutral.wav",
  "ref_text": "参考文本"
}
```

#### GET `/tts/genie-tts/health`

健康检查，返回当前加载状态；若模型未初始化则返回 `503`。

#### GET `/tts/genie-tts/status`

返回 Genie-TTS 当前加载状态与模型信息。

---

### GSV-Lite

**前缀**：`/tts/gsv-lite` — **源码**：`src/lab/api/routes/gsv_lite.py`

#### POST `/tts/gsv-lite/generate`

提交 JSON，直接返回 WAV 音频。

```bash
just test-gsv-lite-generate
```

**请求体**：
```json
{
  "text": "合成文本",
  "ref_audio_path": "models/gsv-tts-lite/<character>/emotions/neutral.wav",
  "ref_text": "参考文本",
  "speaker_audio_path": "models/gsv-tts-lite/<character>/speaker/neutral.wav",
  "top_k": 15,
  "top_p": 1.0,
  "temperature": 1.0,
  "repetition_penalty": 1.35,
  "noise_scale": 0.5,
  "speed": 1.0
}
```

#### GET `/tts/gsv-lite/health`

健康检查，返回当前加载状态；若模型未初始化则返回 `503`。

#### GET `/tts/gsv-lite/status`

返回 GSV-Lite 当前加载状态与模型信息。

---

### Qwen-TTS

**前缀**：`/tts/qwen-tts` — **源码**：`src/lab/api/routes/faster_qwen_tts.py`

基于 faster-qwen-tts，支持非流式和流式（SSE）两种模式。

#### POST `/tts/qwen-tts/generate`

非流式合成，返回完整 WAV 音频。

```bash
just test-qwen-tts-non-stream
```

**参数**（`multipart/form-data`）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `text` | string | 合成文本（必填） |
| `ref_text` | string | 参考文本（可选） |
| `ref_audio` | file | 参考音频文件（可选） |

**响应**：`audio/wav` 二进制流。

#### POST `/tts/qwen-tts/generate/stream`

流式合成，以 SSE（Server-Sent Events）逐块返回音频数据。

```bash
just test-qwen-tts-stream
```

额外参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `chunk_size` | int | 每块 token 数（默认 8，≥1） |

带实时播放的测试：

```bash
just test-qwen-tts-stream-play
```

#### GET `/tts/qwen-tts/health`

健康检查，返回 `{"status": "ok", "service": "faster-qwen-tts"}`。

---

## 🌍 翻译

**前缀**：`/translate` — **源码**：`src/lab/api/routes/deeplx.py`

### POST `/translate/deeplx`

通过 DeepLX API 翻译文本。需要在 `lab.toml` 的 `[agent]` 中配置 `deeplx_api_key`。

```bash
just test-deeplx
```

**请求体**：
```json
{
  "text": "要翻译的文本",
  "source_language": "JA",
  "target_language": "ZH"
}
```

**响应**：
```json
{
  "code": 200,
  "message": "success",
  "source_text": "原文",
  "target_text": "译文"
}
```

### GET `/translate/deeplx/health`

健康检查。仅检测 `deeplx_api_key` 是否已配置，未配置返回 503。

---

## 🔌 WebSocket

**源码**：`src/lab/api/routes/vtuber.py`

### WS `/client-ws`

Open-LLM-VTuber 前端的 WebSocket 连接端点。每个连接分配唯一 `client_uid`，通过 `WebSocketHandler` 管理对话状态。

---

## 🧠 记忆聊天

**前缀**：`/memory` — **源码**：`src/lab/api/routes/chat.py`

需要 `lab.toml` 中 `[agent] memory_chat_profile` 指向一个 profile（如 `profiles/congyin.toml`）。

### POST `/memory/chat`

Memory Chat 端点，带 session 管理、上下文存储、记忆注入和工具调用。长期记忆由 profile 中启用的 `wikimem` 插件承担（markdown 文件记忆，见 ADR-0001）。

---

## 🛠️ 静态文件

| 路径 | 说明 |
|------|------|
| `/web-tool` | 静态 Web 工具页（HTML） |
| `/web-tool/admin/` | 可视化配置管理页，可用于编辑 profile / 插件 / character / TTS 相关配置 |
| `/live2d-models/*` | Live2D 模型资源 |
| `/bg/*` | 背景图片 |
| `/avatars/*` | 头像图片（仅允许 jpg/png/gif/svg） |

如果本地服务跑在默认端口，常用入口就是：

- `http://127.0.0.1:12393/web-tool/`
- `http://127.0.0.1:12393/web-tool/admin/`

---

## 条件加载

路由模块根据 `lab.toml` 中 `[package]` 配置按需加载：

| 配置项 | 加载的路由 |
|--------|-----------|
| `sherpa_asr = true` | `/asr/sherpa/*`、`/asr/reload`、`/asr/sherpa/reload` |
| `qwen_asr = true` | `/asr/qwen-asr/*`、`/asr/reload` |
| `genie_tts = true` | `/tts/genie-tts/*` |
| `gsv_lite = true` | `/tts/gsv-lite/*` |
| `qwen_tts = true` | `/tts/qwen-tts/*` |
| `agent.memory_chat_profile 非空` | `/memory/chat` |

DeepLX (`/translate/*`)、WebSocket (`/client-ws`)、静态文件路由始终加载。


---

## 🌍 翻译

### DeepLX（在线）

需在 `lab.toml` 配置 `[agent.translate.deeplx] api_key`。

```bash
curl -X POST "http://127.0.0.1:12393/translate/deeplx" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "source_language": "EN", "target_language": "ZH"}'
```

### 本地 LLM 翻译（离线）

需在 `lab.toml` 开启 `[package] llm_translate = true` 并配置模型路径。

无需 API Key，完全本地推理。模型首次请求时自动加载，常驻内存。

```bash
# 健康检查
curl http://127.0.0.1:12393/translate/llm/health

# 翻译（只需指定目标语言，源语言自动识别）
curl -X POST "http://127.0.0.1:12393/translate/llm" \
  -H "Content-Type: application/json" \
  -d '{"text": "今天天气真好", "target_language": "EN"}'
```

**支持的 target_language 代码：**
`ZH` `EN` `JA` `FR` `DE` `ES` `PT` `RU` `KO` `AR` `TH` `VI` `IT`

**justfile 快捷测试：**

```bash
just test-llm-translate
```
