# ADR-0003: memU CLI 集成 —— 以 memu-cli 为唯一契约面激活 ADR-0002 的 fallback

- **状态**：Accepted（2026-07-16）
- **日期**：2026-07-16
- **关联**：[ADR-0002](./0002-memu-design-not-dependency)（本 ADR 激活其 fallback）、[ADR-0001](./0001-llm-mode-memory)、[#493](https://github.com/XnneHangLab/XnneHangLab/issues/493)

## 背景

需求：把 memU 作为**与 wikimem 并列的、可选的第二记忆后端**引入，用于对照评测；约束是
**子模块 + 不 pip install**（镜像 [`XnneHangLab-Mirror/memU`](https://github.com/XnneHangLab-Mirror/memU)）。

设计期间上游发生 pivot（2026-07 中旬，复核镜像 `@main` = `aae3d44` 确认）：

1. **`memu-cli` 成为唯一发布/更新的包**；`memu-py` 冻结待归档。仓库 `pyproject.toml` 已改名
   `memu-cli`（v1.5.1），入口是 `memu` CLI + 一组 host adapter 二进制。
2. **CLI 是唯一受支持的集成面**，上游明确按「**短生命周期进程**」设计（`memu/env.py` 文档原话：
   "entrypoint processes are short-lived"）。host adapter（`memu-claude-code` 等）服务于有
   session log 的 coding agent；我们这类程序化宿主直接说基础 `memu` CLI。
3. **memU 不再自带 LLM 抽取**（record seam 移交宿主）：`memu commit` 只持久化宿主准备好的
   `{"recall_files": [{name, track, description, content}], "resource": [...]}`；memory track 的
   recall file **按行切 segment**（空行与 `#` 标题行跳过、去重）——每一行就是一条可检索记忆。
   `memu retrieve` 是 0 LLM 的 embedding 检索（`progressive_retrieve`），stdout 输出 JSON。
4. 配置只剩 **embedding + store**：`MEMU_EMBED_PROVIDER / MEMU_EMBED_MODEL / MEMU_BASE_URL /
   MEMU_API_KEY / MEMU_DB`，解析顺序 = 进程环境 > `~/.memu/config.env`（可用 `MEMU_CONFIG_ENV`
   重定向）> 默认值。
5. 硬约束未变：`requires-python >=3.13` + maturin/Rust 编译核（`memu._core`）。本项目钉在
   3.11，**同进程导入依然不可行**——但「从子模块源码构建 + 进程外运行」依然成立。

## 决策

**以 memu-cli 的 CLI 契约集成 memU：短生命周期子进程 + 宿主侧抽取 + 影子 markdown，实验性 opt-in。**

1. **子模块**：`packages/memU` 固定在 `aae3d44`（镜像已同步上游）；不 pip install、不进 uv
   workspace（根 `pyproject.toml` `[tool.uv.workspace] exclude` 排除）。
2. **传输 = CLI 子进程**（不再有常驻 sidecar/FastAPI shim）：插件每次调用
   `uv run --isolated --no-project --python 3.13 --with packages/memU memu <retrieve|commit>`。
   `--with 子模块` 触发 maturin 源码构建（需 Rust，首次数分钟，uv 之后缓存环境）；
   `--no-project` 与 3.11 workspace 完全隔离。这正是上游设计的运行形态。
3. **抽取在插件侧**（与 wikimem 同构）：`on_after_turn` 后台单次 LLM 调用（默认继承 `lab.toml`
   chat 配置），复用 wikimem 的 `parse_extraction` 契约（category/name/content JSON 数组）。
4. **影子 markdown 是事实源**：条目以 `name：content` 行追加到
   `<memory_dir>/recall/<category>.md`（人可读可改、重启安全），然后把**整个文件**
   `memu commit`——memU 按行 diff 重建 segments，未变的行保留 embedding。
5. **store 隔离**：`MEMU_DB` 指向 `<memory_dir>/memu.sqlite3`，`MEMU_CONFIG_ENV` 指向
   `<memory_dir>/config.env`（默认不存在）——record/inject 两条 seam 共用同一 store 与
   embedding 空间（上游 ADR-0009 的硬要求），且绝不与用户全局 `~/.memu/` 串味。
6. **embedding 端点是硬前置**（commit 与 retrieve 都要向量化）：`embedding_base_url` 留空 =
   插件禁用（警告一次）。抽取 LLM 与 embedding 相互独立配置。
7. **fail-open 与实验性 opt-in 不变**：结构性缺失（uv / 子模块 / embedding 配置）→ 本会话禁用；
   单次调用失败/超时（含首次构建期）→ 本轮跳过。默认不启用，profile `[plugins] enabled` 加
   `"memu"` 才生效。

## 理由

- **契约面选 CLI 而非 import 内部 API**：上游承诺的更新通道只有 memu-cli，且其 env 层明确按
  短生命周期进程设计。子进程形态把耦合面缩到「三个子命令 + 五个环境变量」，升级子模块 pin 时
  内部重构不会波及我们。（备选：常驻 worker 进程 import `memu.app` —— 更快，但耦合内部 API，
  churn 风险正是 ADR-0002 记录过的教训；作为时延不可接受时的逃生门保留，见「后果」。）
- **宿主侧抽取是上游的新契约**（record seam），恰好与 wikimem 插件的既有形态一致——抽取
  prompt / 解析 / 后台任务模式全部复用，两个后端可公平对照。
- **影子 markdown** 与 memU「memory as files」理念和 wikimem 的「人可审查」价值观同向；memU 的
  SQLite 只是索引投影，事实源始终掌握在本地文件里。

## 后果

**正面**
- 集成面最小且受上游支持；无常驻进程、无端口/健康探测/生命周期管理（对比被替换的 FastAPI
  sidecar 方案净删一个包）。
- 记忆事实源是本地 markdown：可 diff、可手改、可回滚；memU 索引可随时由影子文件重建。
- 与 wikimem 共享抽取契约，评测对照公平。

**负面 / 代价**
- **每次召回都付一次子进程成本**（uv 缓存环境解析 + Python 3.13 启动 + embedding HTTP）。
  实测热路径（Windows，本地 embedding mock，空库 retrieve 三次）：**≈ 2.0 s/次**
  （1931/2069/2035 ms，见 #493 验证记录），慢于 wikimem 的进程内毫秒级。可接受为实验代价；
  若不可接受，逃生门是常驻 stdin-loop worker（import `memu.app`，牺牲契约面换时延——单独 ADR 再议）。
- 首次调用触发 maturin 源码构建（需要 **Rust 工具链** + uv 可解析的 Python 3.13），构建期间
  召回 fail-open 不注入。
- 承接 memu-cli 的 Beta 抖动（本次 pivot 本身就是例证：`memorize_workspace` API 三天内被
  `commit` 取代）；缓解 = 子模块 pin + CLI 最小契约面。

**当前已知阻塞（2026-07-16，pin `aae3d44`）**

上游 main 处于 pivot 中途的**不一致状态**：所有 embedding client 的 `embed()` 返回
`tuple[vectors, raw_response]`（`embedding/base.py`），但新的 agentic 面按「裸 vectors 列表」
消费（`agentic.py` 直接 `[0]` 取向量 / `zip(..., strict=True)`）——导致 **`memu commit` 与
带数据的 `memu retrieve` 在该 pin 上不可用**（空库 retrieve 正常，管线其余部分已验证）。
上游 `cleanup-flow-db-embedding` 分支已把 client 收敛为裸列表（但尚未带上 CLI 面）。已上报
上游：[NevaMind-AI/memU#499](https://github.com/NevaMind-AI/memU/issues/499)。处置：插件
fail-open 使该阻塞只表现为「不注入、不记忆」；等上游修复合入、镜像同步后 re-pin 并补跑端到端
smoke。

**复审条件**
- 对照评测显示 memU 无明显收益，或热路径时延不可接受且不值得做 worker 逃生门 → 退回仅 wikimem。
- `memu-cli` 支持 3.11/3.12 或本项目升 3.13 → 重新评估同进程路径。
- 上游 CLI 契约（子命令/载荷 schema）再次破坏性变更 → 重新评估维护成本。

## 实现落点

- 子模块：`packages/memU`（`aae3d44`）
- 插件：`src/lab/plugins/memu/{__init__.py,plugin.toml}`（CLI 子进程 + 宿主侧抽取 + 影子文件）
- workspace 排除：`pyproject.toml` `[tool.uv.workspace] exclude`
- 测试：`tests/test_memu_plugin.py`（假 CLI：注入/fail-open/影子文件/commit 载荷）
- 文档：`docs/guide/architecture/memu-memory.md`（含无外部 key 的本地 smoke 方法）
