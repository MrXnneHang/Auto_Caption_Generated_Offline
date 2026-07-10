# ADR-0001: 记忆管线（memory pipeline）— categories + wiki-links 取代 Neo4j 语义节点

- **状态**：Accepted
- **曾用名**：LLM Mode（五次修订更名：双模框架废弃后，"Mode" 暗示并不存在的并行模式；文件名保留 `0001-llm-mode-memory` 以稳定既有链接）
- **日期**：2026-07-08，修订 2026-07-10（PR #477 评审：检索去 LLM 化、零基础设施约束；二次修订：撤销双模开关，收敛为单管线 + embedding 渐进增强；三次修订：磁盘无不可读真相——索引不落盘，SQLite 移出设计，补可观测性；四次修订：向量不进物理内存——memmap + 量化分层，VectorIndex 可插拔端口（借鉴 mem0），vectors.json 作废改 .npy；五次修订：更名 LLM Mode → 记忆管线）
- **关联**：[#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) / [#468](https://github.com/XnneHangLab/XnneHangLab/issues/468)（设计来源）、[#470](https://github.com/XnneHangLab/XnneHangLab/issues/470) / [#469](https://github.com/XnneHangLab/XnneHangLab/issues/469)（后续：Multi-Character 记忆）、[ADR-0002](./0002-memu-design-not-dependency)

## 背景

memory_bench 的 Neo4j 图目前有 10 种节点类型，但只支撑可视化，不具备检索能力。其中语义层节点（Domain / Topic / Scene / Predicate）本质上是分类标签：

- 白名单式 predicate / entity_type 不灵活，新场景要改 schema
- 每次记忆写入都要走 claim 抽取 → 图谱管线，维护成本高
- 图结构对 LLM 检索并不友好——LLM 更擅长读文本目录和跟随链接，而不是遍历图

## 决策

引入**记忆管线**（曾用名 LLM Mode）：扁平存储 + categories 分类 + wiki-links 跨类关联，取代 Neo4j 语义节点。

### 硬性约束（2026-07-10 评审补充，见 PR #477 评论）

1. **零基础设施**：没有 embedding 模型、向量库、图数据库时系统必须可用——纯文本检索（BM25）兜底，embedding 只是可选增强。
2. **不为记忆等待 LLM**：retrieve 路径 **0 次** LLM 调用；memorize **至多 1 次** LLM 调用且异步后台执行，永不阻塞对话。检索失败/超时 fail-open（注入空内容，对话照常）。
3. **磁盘上不允许有不可读的真相**（三次修订补充）：category markdown 文件是唯一事实源；一切索引/向量都是派生缓存，删除后必须能从文件完整重建。用户和程序员看文件（和操作日志）就能知道记忆发生了什么——不需要打开任何数据库工具，更不需要 docker。

### 数据模型（resource / category / item 三层）

对应 memU ADR-0007 的 L0 → L1 → L2 分层（见 [ADR-0002](./0002-memu-design-not-dependency)）：

- **L0 resource**：原始对话轮次（来源引用，metadata 记 source_conv）
- **L1 category 文件**：每个分类一个 markdown 文件（如 `memory/preferences.md`），即人工可浏览、可编辑的产物
- **L2 item**：category 文件内的条目（段落/列表项），检索与嵌入的基本单元；条目有稳定的 item-name（wiki-link 的目标），内容里带 wiki-links 与 metadata

1. **Categories** 取代 Domain / Topic / Scene / Predicate 节点，如 `daily_life`、`preferences`、`personality`、`reading`。
2. **Wiki-links** 以 `[[category:item-name]]` 格式直接写在条目内容里。检索命中条目后**机械展开**链接（按名字精确查找，默认一跳）拉取关联条目——不走 LLM，不建图存储。
3. **Metadata** 承载结构信息（owner / source_conv / timestamp），不再需要图节点表达。
4. **单一管线，不做双模开关**：记忆管线是唯一的运行时管线；embedding 是管线内按能力启用的**可选增强项**（见"检索"节），不构成第二个模式。mem0 + Qdrant + Neo4j 一套（旧称 RAG Mode）退回 memory_bench 的本职——**基准对照**，迁移期保留为回退后端。

> 修订说明：#471 原文的"LLM Mode / RAG Mode 独立开关"在 2026-07-10 评审中被撤销。理由：简化后的检索（BM25 + 可选 embedding 融合）与"RAG"的分界线不在检索算法，而在**记忆表示**——把它们做成两条并行运行时管线只会重复建设。默认单管线，有 embedding 就在管线内用上，没有就纯文本检索。

### 写入（memorize）——每轮至多 1 次 LLM 调用，异步

对话轮次 → **单次** LLM 抽取调用（提取条目 + 归类 + 生成 wiki-links 一步完成）→ 追加/合并写入 category 文件。挂在 `HookPlugin.on_after_turn` 时机，后台执行，不阻塞下一轮对话。

### 检索（retrieve）——0 次 LLM 调用，同步但 fail-open

同一条管线，按能力渐进增强，无模式切换：

| 场景 | 排序信号 | 相对纯 BM25 的额外成本 |
|---|---|---|
| 无 embedding 模型（默认 / 兜底） | BM25 关键词（中文需分词） | 无 |
| 配置了 embedding 端点 | BM25 分 + 余弦分各自 min-max 归一后融合 | 写入时每批条目 1 次 embedding 调用、查询时 1 次；向量存本地 memmap 缓存，规模分层见"存储形态与可观测性"节，无新增服务 |

查询 → 检索 L2 条目 → 命中条目机械展开 wiki-links（一跳）→ 按 token 预算裁剪注入。

**embedding 换来什么**：中文同义/改写的语义召回（"想去海边" vs "喜欢海"）——BM25 分词后仍是词面匹配。个人记忆库规模小（数千条目量级），BM25 + 良好的 item 命名可能已经够用；是否默认启用 embedding 融合，由 memory_bench probe 语料的命中率对比决定（M2 先纯 BM25 上线，融合作为 M3 可测量的可选项）。收益大于复杂度**只在"融合项"形态下成立**——一旦做成第二条管线就不成立。

### 存储形态与可观测性（2026-07-10 三次修订，见 PR #477 评论）

评审追问：SQLite 同样是黑盒——用户/程序员无法直接看到库里发生了什么。回应：把"数据库"从设计里拿掉，而不是给数据库配可视化工具。

**磁盘上只有三种东西，全部可读或可删**：

| 磁盘产物 | 角色 | 性质 |
|---|---|---|
| `memory/<category>.md` | **唯一事实源** | 人可读、可编辑、可 diff；用户想改记忆就改文件 |
| `journal.jsonl` | 操作日志（append-only） | 每次 memorize/合并/修复一行：时间戳、source_conv、category、item-name、动作。`tail -f` 即实时视图，"记忆发生了什么"的完整答案 |
| `vectors.npy` + `vectors.keys.jsonl`（仅启用 `[embed]` 时存在） | **持久**派生缓存 | memmap 按需分页，从不整体载入 RAM；keys.jsonl 明文记录 item-name + 内容哈希（可读性由它承担，.npy 只是数字矩阵）；删除仍可重建，但重建要重调 embedding 端点（有 API 成本），故增量更新而非启动即弃 |

**索引不落盘**：BM25 索引在启动时扫描 markdown 在内存构建。数千条目量级（个人记忆库）就是几 MB 文本，重建成本可忽略；若未来到十万条量级，才允许引入磁盘缓存作为优化——仍必须满足硬约束 3（可删、可重建、非真相）。SQLite 从设计中移除（BM25 不需要它）。

**向量不进物理内存（四次修订，PR #477 评审）**：embedding 与 BM25 索引的约束不同——全精度向量既不能常驻 RAM（100 万条 ×768 维 float32 ≈ 3 GB），也不能用 JSON 承载（文本编码体积 ×3 且必须整体 parse）。默认实现按规模分层，全部零服务、零 docker：

| 条目规模 | 候选生成 | 常驻 RAM（768 维） | 查询延迟（估，基准实测为准） |
|---|---|---|---|
| ≤ 1 万 | float32 memmap 全量暴力余弦（numpy） | ≈0（OS 页缓存管理热数据） | 数 ms ~ 几十 ms |
| 1 万 ~ 100 万 | 二值量化签名（1 bit/维）常驻内存 Hamming 粗排 → top-K×4 从 memmap 取全精度重排 | 96 B/条：10 万 ≈ 10 MB，100 万 ≈ 96 MB | < 100 ms |
| 超出 / 特殊需求 | `VectorIndex` 端口接可插拔后端（sqlite-vec、Qdrant local 等，extras 可选） | 由后端决定 | 由后端决定 |

- **端口抽象借鉴 mem0**（其 VectorStore 接口 + 默认本地实现的形态）：抄接口，不抄默认值——重后端永远是宿主的选择，不是包的依赖（与 ADR-0002 同一原则在向量层的应用）。
- 二值量化 + 全精度重排是 Qdrant/mem0 生态的同款技术；召回损失（粗排过采样倍数）由 memory_bench probe 实测定，不拍脑袋。
- numpy 归入 `[embed]` extra——纯 Python 余弦在千条以上不可接受（PR #477 评论区已修正）。

**看见检索**：`retrieve(..., explain=True)` 返回打分明细（BM25 分 / 余弦分 / 融合分、wiki-link 展开了哪些条目、token 预算裁掉了什么），适配层可直接落日志。

**零依赖 CLI**（stdlib，随包提供）：`ls` / `show <category>` / `grep` / `explain "<query>"` / `graph --format mermaid|json`——最后一条从 markdown 解析 `[[...]]` 导出 wiki-link 关系图，接替 Neo4j 语义层的可视化职责（配合 #481 退役），宿主前端拿 JSON 自行渲染。全程无 docker、无服务进程。

**历史追溯**：事实源是纯文本文件，`git init` 记忆目录即免费获得全部历史与 diff——包本身不感知 git，不强加。

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
- 索引不落盘意味着每次启动全量扫描重建——数千条目量级可忽略，十万条目量级需按硬约束 3 重新评估磁盘缓存
- 现有 claim/graph 离线管线继续保留用于 benchmark，但实时链路与它分叉，需维护两套心智模型直到语义节点退役完成

**实施**

按里程碑拆分为独立 issue（挂在 [#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) 下）：存储层 → wiki-link 检索 → 插件接入（默认记忆管线 + embedding 可选融合 + mem0 迁移回退）→ Neo4j 语义节点退役。
