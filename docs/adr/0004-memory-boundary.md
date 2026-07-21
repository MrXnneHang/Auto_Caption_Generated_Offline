# ADR-0004: 记忆职责边界 — 框架管确定性机制，应用管需要模型的判断

- **状态**：Proposed（2026-07-21，随 PR 评审定稿）
- **日期**：2026-07-21
- **关联**：[ADR-0001](./0001-llm-mode-memory)（硬约束来源）、[ADR-0003](./0003-memu-cli-integration)、[wikimem ADR 0001–0004](https://github.com/XnneHangLab/wikimem/pull/13)（框架侧对应决策：日记原语、时间检索、向量缓存元数据、接口契约）

## 背景

wikimem 独立成库并即将新增日记原语与时间门控检索（见 wikimem [PR #13](https://github.com/XnneHangLab/wikimem/pull/13) 的 ADR-0001/0002）。随之浮现一批归属问题：时间意图识别放哪？日记由谁写、按什么策略写？情绪算不算记忆？记忆可视化前端走谁的接口？

[ADR-0001](./0001-llm-mode-memory) 的硬约束其实已经画了分界线的雏形："retrieve 0 次 LLM 调用；memorize 至多 1 次、异步、由宿主发起"。本 ADR 把这条线推广成总原则，并逐项裁定归属。

**总原则**：框架只做确定性的机制（规则、数学、IO）；任何需要模型判断的事都在应用侧。embedding 是唯一例外，且必须以"可插拔、可缺席、失败即降级"的方式注入。

一句话记法：**正则是框架的地板，LLM 是应用的天花板，中间不存在第三个解析器。**

## 决策

### 1. 时间意图识别 = 应用侧 tool call

- 可枚举的时间表达（昨天/前天/上周X/X天前/X月X号）由 wikimem 的正则快通道兜底（wikimem ADR-0002），**应用不重复实现**。
- 模糊指称（"上次我们吵架那天""很久以前"）由 LLM 在对话轮内以 tool call 产出结构化 `time_range`，传给 `retrieve(query, time_range=...)`。
- 事件锚定的两跳查询（先检索事件拿到日期，再围绕它开窗）由 tool 编排完成——这是只有应用侧能做的事。
- 两条来路汇合于 retrieve 的同一个参数，无并行链路。

### 2. diary_writing 从 skill prompt 升格为正式 memorize 策略

- 何时写、写什么、什么文风，归 prompt 与角色配置（`prompts/skills/diary_writing` 升格，per-character 开关进 `profiles/*.toml`）。
- **硬约束不破**：每轮仍至多 1 次异步 LLM 调用——单次抽取调用以结构化输出同时产出 (a) wiki 条目（现有 extraction）与 (b) 日记段落（生动短段落：场景、情绪、事实在一起），一次带回分别写入。
- 解析失败 fail-open：丢弃本轮 memorize，journal 留痕，不重试不阻塞。

### 3. 情绪状态留在应用运行时

- 效价/唤醒度这类每轮变化的 runtime 状态（参照 MoeChat 的 emotion_state）**不是记忆**：不进 wikimem、不被检索，由应用插件持有与持久化。
- 事件中的情绪以日记文本的形式进入记忆（经第 2 条的日记段落）。
- 记法：**状态即时，情绪入事。**

### 4. 记忆可视化前端走应用自身路由

- 前端（Electron）经应用自己的 FastAPI/WebSocket 加路由，进程内调用 wikimem API 提供翻阅、按时间检索、按内容搜索。
- **不依赖 wikimem serve**——serve 面向进程外第三方消费者（wikimem ADR-0004），不是宿主链路的一环；宿主继续进程内 import（毫秒级，对比 memu-cli 子进程 2.1–2.4 s/call）。
- UI 长什么样百分之百归应用；框架只保证数据可及。

### 5. 现状追认

extraction prompt、user_id、token 预算等策略参数继续留在插件侧（`src/lab/plugins/wikimem`），不下沉到框架。

## 理由

- 一条原则切完所有归属问题，与 ADR-0001 的硬约束同源，没有新增心智模型。
- 框架保持零 LLM、零策略，可独立发布独立测试；应用换模型、换 prompt、调策略都不动框架。
- 放弃的备选：
  - **意图识别下沉进框架**——框架就得持有 LLM 配置与调用链路，零依赖与"retrieve 0 LLM"双双破产；
  - **日记独立一次 LLM 调用**——每轮 2 次调用，违反 ADR-0001 硬约束 2；
  - **情绪状态进记忆框架**——每轮变化的状态会把 append-only 的事件流污染成高频可变存储，两头不像；
  - **前端走 wikimem serve**——宿主进程内已有 API，多一跳 HTTP 纯属绕路。

## 后果

**正面**

- wikimem 与应用的接缝收敛为：`retrieve(query, time_range)` 一个调用 + memorize 时的两类写入（wiki 条目 / 日记段落）。
- 时间检索的正则部分零成本常开（快通道），LLM 成本只在模型判断需要时发生（tool call 按需触发）。

**负面 / 代价**

- 单次调用同时产出 wiki 条目 + 日记段落，结构化输出更复杂，解析失败面变大（以 fail-open + journal 留痕兜底）。
- tool call 形态的意图识别依赖模型的工具调用质量，弱模型下"该开窗没开窗"会退化为普通语义检索（可接受：答不出 ≠ 答错）。
- 可视化前端的路由与 wikimem API 之间存在薄适配层，需随 wikimem API 版本同步维护。

**实施**

依赖 wikimem ADR-0001/0002 落地后：插件侧改造（extraction 结构化输出扩展、time_range tool 注册）→ 可视化路由 → per-character 配置项。各挂独立 issue。
