# Memory Bench 文档地图

本目录收录 Memory Bench 的工作流文档：管线指南、schema 参考、提示词说明与 server 设计。

> 运行时 prompt 资产（标注/抽取提示词、场景/角色 canon）与自动生成的 schema 参考位于仓库的 `memory_bench/docs/`；本站文档是对整个工作流的说明与补充。

---

## 文档清单

### 总览

- [脚本指南](./scripts-guide) — 离线/实时管线全流程、执行顺序、清理命令。
- [Typing 设计](./typing-design) — memory_bench 类型系统的分阶段设计。

### Server 架构

- [设计理念](./server/design) — 记忆后端定位、mem0 + Neo4j 架构、与 `src/lab` 的关系。
- [路由与端点](./server/routes) — `/memory/search`、`/memory/add`、`/memory/health` 与 OpenAI 兼容代理。

### Schema

- [节点 Schema（离线）](./schema/node) — 由 `export_node_schema.py` 自动生成。
- [边 Schema（离线）](./schema/edge) — 由 `export_edge_schema.py` 自动生成。
- [节点 Schema（实时）](./schema/realtime-node) — 实时管线与离线管线的兼容性对比。
- [边 Schema（实时）](./schema/realtime-edge) — 实时边 schema 与验证方法。
- [锚点与模板](./schema/anchors) — 全链路数据 schema 与真实样例（Event / Mem0 Export / Claim / Entity / Graph IR），带版本号。

### Prompt 设计

- [标注提示词](./prompts/annotator) — 章节文本 → JSONL events 的标注提示词。
- [场景宪法](./prompts/scene-canon) — 世界边界、主题范围与一致性约束。
- [角色圣典](./prompts/persona-canon) — 人设事实、风格与行为边界。
- [Claim 抽取提示词](./prompts/claim-extractor) — mem0 export → claim/entity JSONL（含 predicate/entity_type 白名单、evidence 回链）。

### 脚本详情

[scripts/](./scripts/index) 下有每个管线脚本的独立文档（CLI 参数、输入输出、排错）。

---

## 推荐阅读顺序

1. [脚本指南](./scripts-guide)（先知道怎么跑、产物在哪）
2. [场景宪法](./prompts/scene-canon)（场景边界）
3. [角色圣典](./prompts/persona-canon)（人设边界）
4. [标注提示词](./prompts/annotator)（events 标注）
5. [锚点与模板](./schema/anchors)（schema / 锚点 / 命名 / 真实数据样例）
6. [replay_mem0](./scripts/replay-mem0)（mem0 回放）
7. [Claim 抽取提示词](./prompts/claim-extractor)（claim/entity 抽取）
