# 配置模块

`src/lab/config_manager/` 负责 **TOML 配置加载、Pydantic 校验与显式持久化**。

它的定位很朴素：让 `lab.toml` 永远是一个可直接读取、结构完整、类型可靠的配置对象，而不是一堆随手拼出来的字典。

---

## 核心设计

### Pydantic 驱动

所有配置都由 **Pydantic BaseModel** 管理，这带来三件事：

- 类型安全：字段类型自动校验
- 默认值集中：默认配置直接写在模型里
- 序列化稳定：`model_dump()` 后可以直接回写 TOML

```python
from lab.config_manager import load_settings_file, XnneHangLabSettings

settings = load_settings_file("lab.toml", XnneHangLabSettings)
```

---

## 加载流程

`load_settings_file()` 的工作顺序固定：

1. 搜索配置文件位置
2. 用 `tomllib` 读取 TOML；未找到时构造内存默认值
3. 交给 Pydantic 做校验和默认值补全
4. 仅在调用 `write_settings_file()` 或显式重载配置时写入 TOML

这样读取配置不会意外修改用户文件，同时仍让保存路径获得完整、类型可靠的配置。

---

## 主配置类

`XnneHangLabSettings` 是整个项目的配置入口。当前结构如下：

```python
class XnneHangLabSettings(BaseModel):
    conf_version: str = "v1.6.5"
    asr: ASRSettings
    webui: AudioRecognizeSettings
    agent: AgentSettings
    local_embedding: LocalEmbeddingSetting
    package: PackagesSettings
    root: RootAbsDir
    server: ServerSettings
```

这里的重点不是“字段多”，而是每个子模块都拥有自己的独立模型。这样 UI、服务端、Agent 初始化都能按模块读取，不需要到处手写键名。

---

## Agent 配置分层

`AgentSettings` 当前的关键字段是：

```python
class AgentSettings(BaseModel):
    chat_model: ChatModelSetting
    vision_model: VisionModelSetting
    enable_tool: bool = True
    prompts: PromptSettings
    llm: LLMSettings
    translate_provider: TranslateProvider = "llm"
    translate: TranslateSettings
    user_lang: Literal["ZH", "EN", "JA"] = "ZH"
    speaker_lang: Literal["ZH", "EN", "JA"] = "ZH"
    tts: TTSSettings
    faster_first_response: bool = False
    max_vision_concurrency: int = 4
    require_detailed: bool = True
    structured_history_full_turns: int = 5
    segment_method: Literal["regex", "pysbd"] = "pysbd"
    interrupt_method: Literal["system", "user"] = "user"
    memory_agent_profile: str = "profiles/baoqiao.toml"
    memory_chat_profile: str = "profiles/congyin.toml"
```

其中 `LLMSettings` 现在已经改成“provider 列表 + 名称引用”的结构，而不是把 provider 名字硬编码进字段层级：

```python
class LLMProviderSetting(BaseModel):
    name: str
    llm_api_key: str = ""
    llm_base_url: str = ""
    api_format: Literal["chat_completion"] = "chat_completion"


class LLMSettings(BaseModel):
    providers: list[LLMProviderSetting] = []
```

`chat_model.llm_provider` 和 `vision_model.llm_provider` 会在校验阶段检查：如果填写了 provider 名称，那么它必须能在 `agent.llm.providers` 中找到同名条目。

### 一个重要变化

现在的配置分层已经很明确：

- `lab.toml` 负责**全局运行时配置**（模型 provider、端口、ASR、包开关等）
- `profiles/*.toml` 负责**角色 / 场景配置**（persona、format、plugins、character、TTS 情绪映射）

因此，以下内容**不再属于 `lab.toml`**：

- persona / format prompt
- 角色身份与前端展示字段
- Live2D 模型名
- TTS 文本预处理
- TTS 角色名与 emotion → ref_audio 映射

这些都在 Profile 系统里承接。

另外，`[agent.llm]` 还有一个兼容层：旧版 `[agent.llm.openai]` 这类结构仍然能被读取，但会在模型校验后迁移成统一的 `[[agent.llm.providers]]` 结构。这也是文档里应该优先展示列表写法的原因。

---

## 与 Profile 系统的衔接

运行时 `ServiceContext` 会：

1. 从 `lab.toml` 读取 `memory_agent_profile`
2. 加载对应 `profiles/*.toml`
3. 将 `[character]` 转换为内部 `CharacterSettings`
4. 将 `[character.tts_preprocessor]` 转成 `tts_preprocessor_config`
5. 将 `[character.tts]` 转成 `tts_config`

也就是说，TTS 情绪联动现在不是硬编码，而是 profile 驱动。

详见：[Profile 系统](./profile-system)。

---

## Package 开关

```toml
[package]
sherpa_asr = false
qwen_asr = false
llm_translate = false
local_embedding = false
gsv_lite = false
genie_tts = false
qwen_tts = false
to_do_list = true
yutto_uiya = true
```

`sherpa_asr` 和 `qwen_asr` 可同时开启，各自注册独立路由，互不干扰。

---

## 配置文件位置

默认搜索顺序：

1. `{当前目录}/config/lab.toml`
2. `{XDG_CONFIG_HOME}/lab.toml` 或 Windows 的 `~/AppData/lab.toml`

如果都不存在，`load_settings_file()` 返回内存默认值，不创建配置文件。

---

## 与其他模块的关系

- `service_context.py` 会读取配置并初始化 Agent 与服务上下文
- `server.py` 会根据 `[package]` 开关决定加载哪些路由
- `AgentFactory` 会读取 `[agent]`，再继续进入 Profile / Plugin / ToolManager 流程
- `Profile` 负责角色化配置；`config_manager` 不再直接承载这些角色字段
