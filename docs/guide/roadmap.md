# RoadMap

XnneHangLab 项目的开发路线图与技术债务清理计划。（更新于 2026-07-10）

## 记忆系统：记忆管线（categories + wiki-links）

**状态：** 设计完成（[ADR-0001](/adr/0001-llm-mode-memory)，五次修订），实施中
**优先级：** 高
**设计文档：** [ADR-0001](/adr/0001-llm-mode-memory) | [ADR-0002](/adr/0002-memu-design-not-dependency) | 评审线程 [PR #477](https://github.com/XnneHangLab/XnneHangLab/pull/477)（设计来源 [#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) / [#468](https://github.com/XnneHangLab/XnneHangLab/issues/468) 已关闭，内容固化进 ADR）

用 categories + wiki-links + metadata 的扁平存储取代 Neo4j 语义节点（Domain / Topic / Scene / Predicate）。设计借鉴 memU（不引入其依赖，见 ADR-0002）。曾用名 LLM Mode——双模框架废弃后更名。Neo4j（含结构节点可视化）已随 memory_bench 于 2026-07-10 整体移除，语义关联可视化由 wikimem CLI `graph` 导出接替（M4 wikimem 侧）。

**评审定案（2026-07-10，ADR-0001 修订 2–5）：**

- **单管线**：双模开关撤销；embedding 是管线内按能力启用的可选融合项，不是第二个模式
- **磁盘无不可读真相**：markdown 是唯一事实源，SQLite 出局；可观测性 = `journal.jsonl` 操作日志 + `explain` 检索追踪 + 零依赖 CLI（含 wiki-link 关系图导出，接替 Neo4j 语义可视化）
- **向量不进物理内存**：float32 memmap → 二值量化分层，`VectorIndex` 可插拔端口（借鉴 mem0 的接口、不抄其默认后端）；numpy 归入 `[embed]` extra
- **交付形态**：独立 pip 包（`packages/` uv workspace member），插件退化为薄适配层；PyPI 首发等 M3 基准数字
- **mem0**：已于 2026-07-10 整体移除（连同 memory_bench / Qdrant / Neo4j）——维护成本高于对比价值：基准强依赖 embedding 模型难以公平对比，且已 4 个月未实际使用

**里程碑：**

| 里程碑 | 内容 | Issue | 状态 |
|---|---|---|---|
| M1 | 存储层 — categories + metadata + 扁平条目 | [#478](https://github.com/XnneHangLab/XnneHangLab/issues/478) | 待开工 |
| M2 | 检索 — wiki-link `[[category:item]]` 解析与关联抓取 | [#479](https://github.com/XnneHangLab/XnneHangLab/issues/479) | 待开工 |
| M3 | MemoryPlugin 接入 — 默认记忆管线，embedding 可选融合；以 `packages/` workspace member 交付，基准报告含召回/延迟/RAM/启动列 | [#480](https://github.com/XnneHangLab/XnneHangLab/issues/480) | 插件已合入（#487），真实语料跑数进行中 |
| M4 | Neo4j 退役 + mem0 / Qdrant / memory_bench 移除；wikimem CLI（ls/show/grep/explain/graph） | [#481](https://github.com/XnneHangLab/XnneHangLab/issues/481) | 移除已完成（2026-07-10），CLI 待 wikimem 侧 |

**后续方向：**

- Multi-Character 记忆（[#470](https://github.com/XnneHangLab/XnneHangLab/issues/470) / [#469](https://github.com/XnneHangLab/XnneHangLab/issues/469)）— Agent 画像独立为记忆管线 category + User 模板继承
- ~~mem0 / Neo4j 基准线~~ — 已随 memory_bench 移除；关联召回收益改由 wikimem `bench/link_probe.py` 支撑（展开 on/off 对比：+29pp @14 条 / +50pp @150 条）

## TTS 统一调度

**状态：** 规划中
**优先级：** 中
**关联：** [#402](https://github.com/XnneHangLab/XnneHangLab/issues/402)

统一 TTS 引擎（Genie-TTS / GSV-TTS-Lite / Qwen-TTS）的调度层，集中管理语音资源与情绪配置。

## 插件与感知

- **AudioTriggerPlugin**（[#368](https://github.com/XnneHangLab/XnneHangLab/issues/368)）— 预制音频库 + 大模型触发 + Live2D 联动
- **异步 Screen Observation / Vision Input 插件架构**（[#380](https://github.com/XnneHangLab/XnneHangLab/issues/380)）— 初版已由 `visual_observer` 插件落地（OCR 轮询 + 场景切换检测 + vision boost），作为 agent core 额外输入的通用架构化仍在设计
- **统一 vision pipeline**（[#353](https://github.com/XnneHangLab/XnneHangLab/issues/353)）— 将更多 tool callback image 接入统一视觉管线

## 功能开发

### 独立翻译大模型

**状态：** 规划中
**优先级：** 中

当前翻译依赖外部 DeepLX 服务与本地 GGUF 小模型（`/translate/llm`），计划评估更强的独立翻译模型。

**候选模型：**

- [Tencent-Hunyuan/HY-MT1.5-1.8B](https://modelscope.cn/models/Tencent-Hunyuan/HY-MT1.5-1.8B) — 腾讯混元翻译模型

**待完成：**

- [ ] 模型集成与推理封装
- [ ] 路由层适配（保持 API 兼容）
- [ ] 性能对比测试（vs DeepLX / Qwen2.5-0.5B）

## 技术债务

### CLI 模块定位

**状态：** 待讨论
**优先级：** 低

`cli.py` 当前只用于 ASR 命令行工具，是否保留需要评估。

**选项：**

1. 保留并扩展为完整的 CLI 工具集
2. 移除，ASR 功能通过 API 调用
3. 拆分到独立的 `lab-cli` 包

## 已完成（存档）

| 事项 | 说明 |
|---|---|
| 工具系统重构：Tool / Skill / Plugin 三层架构 | [#262](https://github.com/XnneHangLab/XnneHangLab/issues/262) 设计已分阶段落地：内置 function calling、Plugin 注册 + ToolManager、Skill 文件系统、Hook 机制 + SystemPromptBuilder |
| memory_bench 定位调整 | chat_router 已迁移至 `src/lab`（[#274](https://github.com/XnneHangLab/XnneHangLab/issues/274)），memory_bench 收敛为纯记忆后端（`/memory/search`、`/memory/add` + OpenAI 兼容代理） |

---

_本文档持续更新，反映项目最新规划。_
