# ADR-0002: memU — 借鉴设计而非引入依赖

- **状态**：Accepted（2026-07-10 按 PR #477 评审意见修订后采纳）
- **日期**：2026-07-08，修订 2026-07-10
- **关联**：[ADR-0001](./0001-llm-mode-memory)、[#471](https://github.com/XnneHangLab/XnneHangLab/issues/471)

## 背景

计划把 [memU](https://github.com/NevaMind-AI/memU)（NevaMind-AI，Apache-2.0，~14k stars，AI companion 记忆框架）引入为记忆插件。2026-07 调研结论：

1. **Python 版本硬阻塞**：`memu-py` 1.5.1 要求 `requires-python >= 3.13`，本项目为 Python 3.11。唯一兼容 3.11 的版本是 2025-08 的 0.1.x（API 已废弃）。5 个月内 Python floor 改了 4 次。
2. **没有 wiki-link 机制**：memU 的跨分类关联靠 entry↔category 关系边 + 多分类归属 + embeddings，内容内链接（`[[...]]`）不存在——而这正是 ADR-0001 的核心差异化设计。引入 memU 意味着放弃差异化而不是实现它。
3. **架构已转向 DB-first**：v1.x 的事实存储是 SQLModel（SQLite / Postgres+pgvector），markdown 目录只是默认关闭的导出投影。"markdown 文件式记忆"是 memU v0.1 的旧印象。
4. **Beta 级 API 剧变**：`MemoryItem/MemoryCategory` → `RecallEntry/RecallFile` 重命名，0.2 → 1.0 只用了 3 个月；`memorize` 只接受文件式 `resource_url`（对话需先落盘）；`dedupe_merge` 是文档标明的占位 no-op。
5. **依赖与部署负担**：依赖树含 langchain-core / sqlmodel / alembic / anthropic / numpy≥2.3；`memU-server`（独立仓库）是 AGPL-3.0 + Postgres + pgvector + Temporal，桌面应用不可捆绑。

> **2026-07-10 更新**（PR #477 评审）：复核了 memU 最新 ADR（[0006](https://github.com/NevaMind-AI/memU/blob/main/docs/adr/0006-from-memory-item-category-to-tracked-workspace-memorization.md) / [0007](https://github.com/NevaMind-AI/memU/blob/main/docs/adr/0007-three-independent-memory-lines-wiki-graph.md) / [0008](https://github.com/NevaMind-AI/memU/blob/main/docs/adr/0008-two-integration-surfaces-hooks-and-api.md)）。memU 正在放弃旧的 memorize/retrieve：检索收敛为**单趟混合搜索**（BM25 + embedding 融合，0 次 LLM 调用，明确无图、无多跳、无 sufficiency 管线），写入收敛为 trajectory 单次抽取 + 异步后台（hook 契约 on_turn / on_prompt）。下方借鉴清单已同步到该终态。

## 决策

**不引入 `memu-py` 依赖。** 在记忆管线（ADR-0001）的自研实现中借鉴 memU 已被验证的设计：

1. **L0 → L1 → L2 数据分层**（memU ADR-0007）：resource（原始来源）→ category 文档（每分类一个 markdown 文件）→ item 切片（检索基本单元）。resource / item / category 三层保留。
2. **提取 prompt 设计原则**：条目自包含（self-contained）、与语料同语言（中文语料产中文记忆）、叙述者/主体区分、排除短时效信息（no-ephemera）；memory_type 六类（profile / event / knowledge / behavior / skill / tool）作 categories 顶层参考
3. **单趟混合检索，检索不调 LLM**（memU ADR-0007 终态）：BM25 关键词为底、embedding 余弦为可选融合（min-max 归一）。memU 已放弃旧的 route_intention / sufficiency 多级 LLM 管线与图遍历——直接采用其终态，不重走弯路
4. **集成时序 = hook 契约**（memU ADR-0008）：写入异步后台（`on_turn` ≈ 本项目 `HookPlugin.on_after_turn`）、注入同步临界路径 + token 预算 + fail-open（`on_prompt` ≈ `on_before_turn`）

### Fallback（备选，暂不执行）

若自研实现成本超出预期：uv sidecar 方案——`uv run --python 3.13 --with memu-py` 拉起独立进程，包一层 localhost FastAPI shim，固定 1.5.x 版本，SQLite 后端，embedding 指向用户自己的 LLM 供应商或本地 Ollama。代价：桌面应用多一个进程生命周期要管理，且承担 Beta API 升级风险。

## 理由

- ADR-0001 的设计与 memU 核心理念重合度约 80%（categories、原子条目、多分类归属、LLM/RAG 双检索、user-scoped metadata）——重合部分借鉴设计即可获得；剩下 20%（wiki-links、扁平可审查存储）恰是 memU 没有的
- 三条集成路径全部有结构性成本：in-process 被 Python 3.13 阻塞；sidecar 增加进程管理 + API churn 风险；memU-server 直接不可行（AGPL + 重基建）
- 全项目升级 Python 3.13 是先决条件级别的大动作（Live2D / ONNX / TTS 依赖链需全部验证），不应由一个记忆插件驱动

## 后果

**正面**

- 无 Python 版本冲突、无 Beta API 升级风险、依赖树不膨胀
- wiki-links 差异化设计得以保留
- 提取 prompt / 检索管线按中文语料与桌面场景定制

**负面 / 代价**

- 提取与检索管线需自行实现和调优（memU 的 prompt 可作起点：`src/memu/prompts/memory_type/*.py`，Apache-2.0）
- 无法直接受益于 memU 上游迭代

**复审条件**（满足任一时重新评估本决策）

- `memu-py` 恢复支持 Python 3.11/3.12，或本项目完成 3.13 升级
- memU 引入 in-content links 机制
- 自研记忆管线实现两个里程碑后效果不达预期（届时启用 sidecar fallback）
