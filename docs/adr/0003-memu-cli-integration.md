# ADR-0003: memU 双面集成 —— memu-cli 先行，memu-py 就绪后接入，皆从子模块源码构建

- **状态**：Accepted（2026-07-16；2026-07-18 修订：双面连接策略 + 上游回归解决 + uv 缓存坑）
- **日期**：2026-07-16，修订 2026-07-18
- **关联**：[ADR-0002](./0002-memu-design-not-dependency)（本 ADR 激活其 fallback）、[ADR-0001](./0001-llm-mode-memory)、[#493](https://github.com/XnneHangLab/XnneHangLab/issues/493)、上游 [memU ADR-0008](https://github.com/NevaMind-AI/MemU/blob/main/docs/adr/0008-two-integration-surfaces-hooks-and-api.md)

## 背景

### 动机：contributor 的 dogfooding 回路

维护者是 memU 的 **contributor**。把 memU 接进自己的 workspace 常驻使用，目的不止「与 wikimem
对照评测」，更是**吃自己的狗粮**：在真实高频使用中同时发现 memU 与本系统两边的问题与改进点，
反哺上游。这条回路在集成首日即被验证：

- 集成 smoke 发现 embed 契约回归 → 上报 [memU#499](https://github.com/NevaMind-AI/memU/issues/499)
  → 上游**当日**以 [#504](https://github.com/NevaMind-AI/MemU/pull/504) 修复；
- 集成过程还实测出 uv 路径源的静默缓存坑（见「后果」）与 Windows 非 UTF-8 代码页管道乱码
  （上游 [#513](https://github.com/NevaMind-AI/MemU/pull/513) 同期修复）。

约束不变：**子模块（镜像 [`XnneHangLab-Mirror/memU`](https://github.com/XnneHangLab-Mirror/memU)）
源码构建，永不 pip install**——对下述两个集成面都成立。

### 上游架构：两个分层的集成面（memU ADR-0008）

上游不是「只剩 memu-cli」，而是**两个集成面、一个 base plane**（共享同一 per-project store，
可自由混用）：

- **Surface A —— zero-code hooks**（`memu-cli` + host adapters）：面向「装上就有记忆」的
  drop-in 用户。hook 契约两条 seam：`on_turn`（回合后异步记录轨迹 + memorize，永不阻塞）、
  `on_prompt`（生成前同步 retrieve 注入，token 预算，fail-open）。
- **Surface B —— programmatic API**（`memu-py`）：面向把 memU 内嵌进自己 agent 的 builder，
  在代码里直接调 retrieve / memorize（in-process service 或 CLI/JSON），自主掌控时机、批量与
  scope。

`memu-py` 正在经历**大重构**（ADR-0008 的 trajectory-as-source 方案：轨迹为唯一原始源，
memory / skill / project 三线从同一轨迹语义抽取；CLI 收敛为 `memu memorize` / `memu retrieve`
唯一命令对，`-workspace` 命令**无弃用期移除**）。**重构后的 memu-py 尚未就绪**；就绪后接入。

### 硬约束

`requires-python >=3.13` + maturin/Rust 编译核（`memu._core`）；本项目钉在 3.11：

- CLI 面必然**进程外**（短生命周期子进程，上游明确按此设计——`memu/env.py`：
  "entrypoint processes are short-lived"）。
- memu-py 面的进程形态**待其就绪时定**：若重构后支持 3.11 → 进程内 import；若仍 3.13 →
  常驻 worker 进程 import（即本 ADR 初版「逃生门」的正式化，热路径从秒级降到毫秒-亚秒级）。

## 决策

**双面连接，不二选一；两面都从 `packages/memU` 子模块源码构建。**

### 1. memu-cli 连接（Surface A 语义，已落地）

1. **子模块**：`packages/memU` 固定 mirror main（当前 `f51673e`，含 #504 修复）；不进 uv
   workspace（根 `pyproject.toml` `[tool.uv.workspace] exclude` 排除）。
2. **传输 = CLI 短生命周期子进程**：插件每次调用
   `uv run --isolated --no-project --python 3.13 --with packages/memU memu <retrieve|commit>`；
   `--no-project` 与 3.11 workspace 完全隔离；子进程环境强制 `PYTHONIOENCODING=utf-8`
   （非 UTF-8 Windows 代码页的管道乱码防护，任何 pin 都成立）。
3. **抽取在插件侧**（上游 record seam 语义，与 wikimem 同构）：`on_after_turn` 后台单次 LLM
   调用（默认继承 `lab.toml` chat 配置），复用 wikimem 的 `parse_extraction` 契约。本项目的
   `HookPlugin.on_before_turn / on_after_turn` 与上游 hook 契约 `on_prompt / on_turn` 一一对应
   ——**这个插件事实上就是本项目自己的 host adapter**。
4. **影子 markdown 是事实源**：条目以 `name：content` 行追加到
   `<memory_dir>/recall/<category>.md`（人可读可改、可 diff 回滚），整文件 `memu commit`；
   memU 按行 diff 重建 segments，SQLite 只是索引投影，可随时由影子文件重建。
5. **store 隔离**：`MEMU_DB` / `MEMU_CONFIG_ENV` 指向 `<memory_dir>`——record/inject 两条
   seam 共用同一 store 与 embedding 空间（上游 ADR-0009 硬要求），绝不与全局 `~/.memu/` 串味。
6. **embedding 端点是硬前置**（commit/retrieve 都要向量化）：留空即禁用（警告一次）。
7. **fresh-build guard**（实测坑的对策，见「后果」）：插件用 marker 记录子模块 commit，
   re-pin 后自动 touch `pyproject.toml` 迫使 uv 重建，杜绝静默旧构建。
8. **fail-open 与实验性 opt-in**：结构性缺失 → 本会话禁用；单次失败/超时 → 本轮跳过；默认
   不启用。

### 2. memu-py 连接（Surface B，待上游重构就绪）

- 时机：上游 trajectory-as-source 重构落地、memu-py 形态稳定后接入；接入时**修订本 ADR 或另立
  ADR** 确定进程形态（3.11 进程内 vs 3.13 常驻 worker）、与 CLI 面的共存方式（同一 store 可
  混用是上游保证）及配置面。
- 预期分工：CLI 面 = 与上游 drop-in 路径同构的基线（对照评测、随上游演进）；PY 面 = 热路径
  性能（毫秒-亚秒级检索）与代码级控制（自定批量/scope）。**两面并存，不互相取代。**
- 同样**只从子模块源码构建**。

## 理由

- **契约面选 CLI 而非 import 内部 API（现阶段）**：CLI 是上游当前唯一受支持的稳定面；子进程
  形态把耦合缩到「三个子命令 + 五个环境变量」。Surface B 的 Python API 等上游自己宣布就绪，
  不追它的重构中间态——ADR-0002 记录过追 Beta 内部 API 的教训，本次 pivot 与 #499 都是新证据。
- **双面并存是上游设计直接支持的**（分层共享 store，可自由混用），不是我们的私造组合。
- **宿主侧抽取与影子 markdown** 与上游 record-seam 语义、与 wikimem 的「人可审查」价值观同向；
  两个后端共享抽取契约，评测对照公平。

## 后果

**正面**

- 集成面最小且受上游支持；无常驻进程、无端口/健康探测（对比被替换的 FastAPI sidecar 净删一包）。
- 记忆事实源是本地 markdown：可 diff、可手改、可回滚；索引可重建。
- **contributor 回路已被证明**：#499 当日修复（#504）；后续 memu-py 接入延续同一回路。

**负面 / 代价**

- **每次召回付一次子进程成本**：实测热路径（Windows，本地 embedding mock，带数据 retrieve
  三次）**2.1–2.4 s/次**，慢于 wikimem 进程内毫秒级。可接受为实验代价；根治靠 Surface B
  （memu-py）接入。
- 首次调用触发 maturin 源码构建（需 **Rust 工具链** + uv 可解析的 Python 3.13），构建期间
  召回 fail-open 不注入。
- **uv 路径源静默缓存坑（实测）**：uv 对路径依赖的 cache key 只看 `pyproject.toml` 等构建
  文件的 **mtime**。子模块 re-pin 后若版本号没变、`pyproject.toml` 字节未变（checkout 不碰它
  → mtime 不变），uv 会**静默复用旧构建**——`--refresh-package` 与 `uv cache clean <pkg>`
  均无效，唯 touch 构建文件有效。对策：插件内置 fresh-build guard（marker + touch，自动）；
  手动跑 CLI 时 re-pin 后需 `touch packages/memU/pyproject.toml`。可向上游建议在其
  `pyproject.toml` 加 `[tool.uv] cache-keys = [{ file = "pyproject.toml" }, { git = { commit = true } }]`
  一劳永逸。
- 承接 memU 的 Beta 抖动：**已宣告的下一个破坏性变更**是 CLI 命令收敛（`memu memorize` /
  `memu retrieve` 成为唯一命令对，现用的 `commit` / `list-files` / `-workspace` 世代整体退场，
  无弃用期）——未来 re-pin 跨过该 cut 时插件需同步适配。缓解 = 子模块 pin + 最小契约面 +
  contributor 对上游 roadmap 的一手掌握。

**已解决（历史记录）**

- ~~上游 main embed 契约回归（client 返回元组、agentic 面按裸列表消费，`commit`/带数据
  `retrieve` 不可用）~~：上报 [memU#499](https://github.com/NevaMind-AI/memU/issues/499)
  （2026-07-16）→ 上游当日 [#504](https://github.com/NevaMind-AI/MemU/pull/504) 修复 →
  re-pin `f51673e` 后 keyless round-trip smoke（commit → retrieve 命中返回）**通过**
  （2026-07-18）。

**复审条件**

- **memu-py 重构就绪** → 启动 Surface B 接入（修订本 ADR：进程形态、配置、与 CLI 面分工）。
- 对照评测显示 memU 无明显收益，或维护成本超预期 → 退回仅 wikimem。
- 上游 CLI 命令 cut 落地 → re-pin + 插件适配（`commit` → 新 `memorize` 语义映射）。

## 实现落点

- 子模块：`packages/memU`（mirror main `f51673e`）
- 插件：`src/lab/plugins/memu/{__init__.py,plugin.toml}`（CLI 子进程 + 宿主侧抽取 + 影子文件
  + fresh-build guard + UTF-8 stdio）
- workspace 排除：`pyproject.toml` `[tool.uv.workspace] exclude`
- 测试：`tests/test_memu_plugin.py`（假 CLI + env 隔离不变量 + fresh-build guard）
- 文档：`docs/guide/architecture/memu-memory.md`（含 keyless smoke 与 re-pin runbook）
- 待接入：memu-py（Surface B）—— 上游就绪后另行修订
