# 🌍 翻译引擎

XnneHangLab 支持两种翻译引擎，通过 `translate_provider` 切换：

| 引擎 | 说明 | 是否需要 API Key | 是否离线 |
|---|---|---|---|
| `llm` | 本地 Qwen2.5-0.5B GGUF 推理 | ❌ 不需要 | ✅ 完全离线 |
| `deeplx` | DeepLX 在线 API | ✅ 需要 | ❌ 需联网 |

翻译功能目前用于 TTS 文本的跨语言转换（`tts_text`），对精度要求不高，短句效果够用。

---

## 快速开始（本地 LLM）

### 1. 开启 package 开关并配置

`config/lab.toml`：

```toml
[package]
llm_translate = true

[agent]
translate_provider = "llm"

[agent.translate.llm]
model_path = "./models/qwen2.5-0.5b-instruct-q8_0.gguf"
n_gpu_layers = 0   # 0 = 纯 CPU，-1 = 全 GPU（需 CUDA）
```

### 2. 下载模型

通过 **Launcher 的 Models 页面** 下载翻译模型；或手动下载 `Qwen/Qwen2.5-0.5B-Instruct-GGUF` Q8_0 量化（约 676 MB）放到 `./models/`。

### 3. 启动服务

```bash
just server
```

### 4. 测试

```bash
curl http://localhost:12393/translate/llm/health
curl -X POST http://localhost:12393/translate/llm \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world", "target_language": "ZH"}'
```

---

## 快速开始（DeepLX）

### 1. 配置

```toml
[agent]
translate_provider = "deeplx"

[agent.translate.deeplx]
api_key = "YOUR_DEEPLX_API_KEY"
```

### 2. 测试

```bash
just test-deeplx
```

---

## 翻译质量参考

> 模型：Qwen2.5-0.5B-Instruct Q8_0，用于 TTS 文本转换，短句质量够用。

| 方向 | 原文 | 译文 |
|---|---|---|
| EN→ZH | The rain finally stopped this afternoon. | 下午这阵雨终于停止了。 |
| ZH→EN | 今天下午的会议比预期更顺利。 | The meeting today was more successful than expected. |
| JA→ZH | 桜の花が満開です。 | 樱花盛开。美得很。 |
| FR→ZH | La bibliothèque ferme plus tôt le vendredi. | 居民区图书室周五关门更早。 |
| KO→ZH | 이것은 테스트입니다. | 这是测试。 |

---

## API 参考

### POST /translate/llm

**请求：**

```json
{
  "text": "Hello world",
  "target_language": "ZH"
}
```

**支持的 `target_language` 代码：**

`ZH` `EN` `JA` `FR` `DE` `ES` `PT` `RU` `KO` `AR` `TH` `VI` `IT`

> source_language 无需指定，模型自动识别输入语言。

**响应：**

```json
{
  "code": 200,
  "message": "success",
  "source_text": "Hello world",
  "target_text": "你好，世界"
}
```

### GET /translate/llm/health

引擎已加载时返回 `200 {"status": "ok"}`，未加载时返回 `503`。

---

## 技术说明

- 推理库：`llama-cpp-python`，自包含预编译 wheel，`pip install` 即可，无需额外安装 DLL 或依赖
- 模型常驻内存，单例管理，首次请求时自动加载
- FastAPI 路由使用 `run_in_executor` 避免阻塞事件循环
- Prompt 策略：只约束 target_language，source_language 自动识别

```
system: "Translate to {target_language_full}. Output translation only."
user:   {text}
```

- Windows 安装时会从预编译 wheel 拉取，避免本地编译：

```toml
# pyproject.toml
[tool.uv]
extra-index-url = ["https://abetlen.github.io/llama-cpp-python/whl/cpu"]
```
