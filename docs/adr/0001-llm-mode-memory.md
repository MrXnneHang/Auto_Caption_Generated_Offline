# ADR-0001: LLM Mode 记忆系统 — categories + wiki-links 取代 Neo4j 语义节点

- **状态**：Accepted
- **日期**：2026-07-08，修订 2026-07-10（PR #477 评审：检索去 LLM 化、零基础设施约束；二次修订：撤销双模开关，收敛为单管线 + embedding 渐进增强）
- **关联**：[#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) / [#468](https://github.com/XnneHangLab/XnneHangLab/issues/468)（设计来源）、[#470](https://github.com/XnneHangLab/XnneHangLab/issues/470) / [#469](https://github.com/XnneHangLab/XnneHangLab/issues/469)（后续：Multi-Character 记忆）、[ADR-0002](./0002-memu-design-not-dependency)

## 背景

memory_bench 的 Neo4j 图目前有 10 种节点类型，但只支撑可视化，不具备检索能力。其中语义层节点（Domain / Topic / Scene / Predicate）本质上是分类标签：

- 白名单式 predicate / entity_type 不灵活，新场景要改 schema
- 每次记忆写入都要走 claim 抽取 → 图谱管线，维护成本高
- 图结构对 LLM 检索并不友好——LLM 更擅长读文本目录和跟随链接，而不是遍历图

## 决策

引入 **LLM Mode**：扁平存储 + categories 分类 + wiki-links 跨类关联，取代 Neo4j 语义节点。

### 硬性约束（2026-07-10 评审补充，见 PR #477 评论）

1. **零基础设施**：没有 embedding 模型、向量库、图数据库时系统必须可用——纯文本检索（BM25）兜底，embedding 只是可选增强。
2. **不为记忆等待 LLM**：retrieve 路径 **0 次** LLM 调用；memorize **至多 1 次** LLM 调用且异步后台执行，永不阻塞对话。检索失败/超时 fail-open（注入空内容，对话照常）。

### 数据模型（resource / category / item 三层）

对应 memU ADR-0007 的 L0 → L1 → L2 分层（见 [ADR-0002](./0002-memu-design-not-dependency)）：

- **L0 resource**：原始对话轮次（来源引用，metadata 记 source_conv）
- **L1 category 文件**：每个分类一个 markdown 文件（如 `memory/preferences.md`），即人工可浏览、可编辑的产物
- **L2 item**：category 文件内的条目（段落/列表项），检索与嵌入的基本单元；条目有稳定的 item-name（wiki-link 的目标），内容里带 wiki-links 与 metadata

1. **Categories** 取代 Domain / Topic / Scene / Predicate 节点，如 `daily_life`、`preferences`、`personality`、`reading`。
2. **Wiki-links** 以 `[[category:item-name]]` 格式直接写在条目内容里。检索命中条目后**机械展开**链接（按名字精确查找，默认一跳）拉取关联条目——不走 LLM，不建图存储。
3. **Metadata** 承载结构信息（owner / source_conv / timestamp），不再需要图节点表达。
4. **单一管线，不做双模开关**：LLM Mode 是唯一的运行时记忆管线；embedding 是管线内按能力启用的**可选增强项**（见"检索"节），不构成第二个模式。mem0 + Qdrant + Neo4j 一套（旧称 RAG Mode）退回 memory_bench 的本职——**基准对照**，迁移期保留为回退后端。

> 修订说明：#471 原文的"LLM Mode / RAG Mode 独立开关"在 2026-07-10 评审中被撤销。理由：简化后的 LLM Mode 检索（BM25 + 可选 embedding 融合）与"RAG"的分界线不在检索算法，而在**记忆表示**——把它们做成两条并行运行时管线只会重复建设。默认 LLM Mode，有 embedding 就在管线内用上，没有就纯文本检索。

### 写入（memorize）——每轮至多 1 次 LLM 调用，异步

对话轮次 → **单次** LLM 抽取调用（提取条目 + 归类 + 生成 wiki-links 一步完成）→ 追加/合并写入 category 文件。挂在 `HookPlugin.on_after_turn` 时机，后台执行，不阻塞下一轮对话。

### 检索（retrieve）——0 次 LLM 调用，同步但 fail-open

同一条管线，按能力渐进增强，无模式切换：

| 场景 | 排序信号 | 相对纯 BM25 的额外成本 |
|---|---|---|
| 无 embedding 模型（默认 / 兜底） | BM25 关键词（中文需分词） | 无 |
| 配置了 embedding 端点 | BM25 分 + 余弦分各自 min-max 归一后融合 | 写入时每批条目 1 次 embedding 调用、查询时 1 次；向量存 SQLite/JSON，暴力余弦，无新增服务 |

查询 → 检索 L2 条目 → 命中条目机械展开 wiki-links（一跳）→ 按 token 预算裁剪注入。

**embedding 换来什么**：中文同义/改写的语义召回（"想去海边" vs "喜欢海"）——BM25 分词后仍是词面匹配。个人记忆库规模小（数千条目量级），BM25 + 良好的 item 命名可能已经够用；是否默认启用 embedding 融合，由 memory_bench probe 语料的命中率对比决定（M2 先纯 BM25 上线，融合作为 M3 可测量的可选项）。收益大于复杂度**只在"融合项"形态下成立**——一旦做成第二条管线就不成立。

### 与 Neo4j 的关系

- 结构节点（Agent / Character / User / Conversation）**保留**，继续用于可视化
- 语义节点由 categories 接管，实时管线停止生成语义节点
- mem0 / Neo4j 基准线退回 memory_bench 基准对照定位；embedding + graph traversal 若未来复活，以基准数据立项为研究线，不是运行时并行模式

## 理由

- 分类文件 + 链接是人和 LLM 都能直接阅读的组织方式；检索用纯文本搜索 + 机械链接展开，不需要向量库和图数据库
- 扁平存储 + metadata 让记忆条目可以直接被人工审查、编辑、diff
- 业界验证：memU（14k stars）最新设计（其 ADR-0007/0008）与本方案收敛到同一形态——分类 markdown 文件 + 单趟无 LLM 检索 + 无图存储，并明确放弃了多级 LLM 检索管线；wiki-links 是我们在其之上的差异化设计（memU 放弃的是实体图引擎，不是文内链接——机械展开的文内链接成本近乎为零）
- 放弃的备选：继续扩展 Neo4j 语义层（检索仍缺失、维护成本继续上升）；全面转向向量 RAG（丢失可解释性，且与"AI 如何真的记得"的探索方向不符）；LLM 多级检索管线（每轮 2–3 次 LLM 调用，延迟不可接受，memU 也已放弃该路线）

## 后果

**正面**

- 记忆写入链路大幅简化（不再强制走 claim 抽取 + 图谱管线）
- 对话零等待：读路径无 LLM 调用，写路径异步后台
- 无基础设施依赖：embedding / 向量库 / 图数据库都不是前提
- 分类体系可以由 LLM 动态扩展，无 schema 白名单
- 记忆内容（markdown 文件）可人工审查与编辑

**负面 / 代价**

- 无 embedding 时 BM25 对中文需要分词支持（jieba 或字符 n-gram），召回质量需要基准验证
- wiki-links 的一致性需要写入侧保证（链接目标不存在时需容忍或修复）
- 现有 claim/graph 离线管线继续保留用于 benchmark，但实时链路与它分叉，需维护两套心智模型直到语义节点退役完成

**实施**

按里程碑拆分为独立 issue（挂在 [#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) 下）：存储层 → wiki-link 检索 → 插件接入（默认 LLM Mode + embedding 可选融合 + mem0 迁移回退）→ Neo4j 语义节点退役。
