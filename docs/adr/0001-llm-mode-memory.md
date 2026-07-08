# ADR-0001: LLM Mode 记忆系统 — categories + wiki-links 取代 Neo4j 语义节点

- **状态**：Accepted
- **日期**：2026-07-08
- **关联**：[#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) / [#468](https://github.com/XnneHangLab/XnneHangLab/issues/468)（设计来源）、[#470](https://github.com/XnneHangLab/XnneHangLab/issues/470) / [#469](https://github.com/XnneHangLab/XnneHangLab/issues/469)（后续：Multi-Character 记忆）、[ADR-0002](./0002-memu-design-not-dependency)

## 背景

memory_bench 的 Neo4j 图目前有 10 种节点类型，但只支撑可视化，不具备检索能力。其中语义层节点（Domain / Topic / Scene / Predicate）本质上是分类标签：

- 白名单式 predicate / entity_type 不灵活，新场景要改 schema
- 每次记忆写入都要走 claim 抽取 → 图谱管线，维护成本高
- 图结构对 LLM 检索并不友好——LLM 更擅长读文本目录和跟随链接，而不是遍历图

## 决策

引入 **LLM Mode**：扁平存储 + categories 分类 + wiki-links 跨类关联，取代 Neo4j 语义节点。

1. **Categories** 取代 Domain / Topic / Scene / Predicate 节点，如 `daily_life`、`preferences`、`personality`、`reading`。分类即目录，LLM 检索时按分类浏览。
2. **Wiki-links** 以 `[[category:item-name]]` 格式直接写在记忆内容里。LLM 检索时通过链接抓取关联条目，实现跨分类跳转。
3. **Metadata** 承载结构信息（owner / source_conv / timestamp），不再需要图节点表达。
4. **独立开关**：LLM Mode 与 RAG Mode 各自独立启停，常态下同一时间只跑一种模式。

### 与 Neo4j 的关系

- 结构节点（Agent / Character / User / Conversation）**保留**，继续用于可视化
- 语义节点由 categories 接管，实时管线停止生成语义节点
- RAG Mode 未来独立演进（embedding + graph traversal），不受本决策影响

## 理由

- 分类 + 链接是 LLM 原生可读的组织方式：检索 = 读目录 + 跟链接，不需要向量库和图查询
- 扁平存储 + metadata 让记忆条目可以直接被人工审查、编辑、diff
- 业界验证：memU（14k stars）的 categories + memory-type 体系证明了"分类目录"这条路线可行，且它完全没有图数据库（见 [ADR-0002](./0002-memu-design-not-dependency)）；wiki-links 是我们在其之上的差异化设计
- 放弃的备选：继续扩展 Neo4j 语义层（检索仍缺失、维护成本继续上升）；全面转向向量 RAG（丢失可解释性，且与"AI 如何真的记得"的探索方向不符）

## 后果

**正面**

- 记忆写入链路大幅简化（不再强制走 claim 抽取 + 图谱管线）
- 分类体系可以由 LLM 动态扩展，无 schema 白名单
- 记忆内容可人工审查与编辑

**负面 / 代价**

- LLM Mode 检索每轮消耗额外 LLM 调用（读目录、跟链接）
- wiki-links 的一致性需要写入侧保证（链接目标不存在时需容忍或修复）
- 现有 claim/graph 离线管线继续保留用于 benchmark，但实时链路与它分叉，需维护两套心智模型直到语义节点退役完成

**实施**

按里程碑拆分为独立 issue（挂在 [#471](https://github.com/XnneHangLab/XnneHangLab/issues/471) 下）：存储层 → wiki-link 检索 → 插件双模开关 → Neo4j 语义节点退役。
