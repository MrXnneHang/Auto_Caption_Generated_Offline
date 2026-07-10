# Memory Bench 脚本指南

> **路由索引文件** — 本文档作为脚本目录的入口，讲述管线整体流程和 Server 架构。
> 每个脚本的详细说明请参阅 [`scripts/`](./scripts/) 下的独立文档。

---

## 目录结构

```
docs/memory-bench/
├── scripts-guide.md         # 本文件（路由索引）
├── scripts/                 # 脚本详情目录（每脚本一页）
├── schema/                  # 节点 / 边 / 锚点 schema 参考
├── prompts/                 # 提示词设计说明
└── server/                  # server 设计与路由文档
```

---

## 一、离线管线（Offline Pipeline）

离线管线用于 benchmark replay，将原始章节文本逐步转换为 Neo4j 图谱数据。

### 1.1 数据构建流程

```
章节原文 → [build_index] → index.json
              ↓
    [annotate_all] → events/by_chapter/*.jsonl
              ↓
   [compile_events] → events/compiled/all.jsonl
```

**相关脚本**：
- [`build_index.md`](./scripts/build-index.md) — 生成章节索引
- [`annotate_all.md`](./scripts/annotate-all.md) — LLM 标注为 events
- [`compile_events.md`](./scripts/compile-events.md) — 拼接为全量 JSONL

### 1.2 Mem0 回放流程

```
events/compiled/all.jsonl
         ↓
[replay_mem0 ingest] → Mem0（Qdrant 存储）
         ↓
[replay_mem0 export] → logs/replay_mem0/export_*.jsonl
```

**相关脚本**：
- [`replay_mem0.md`](./scripts/replay-mem0.md) — ingest / probe / export 三合一

### 1.3 Claim 抽取流程

```
export_*.jsonl
     ↓
[claimify_all] → claims/by_conv/*.jsonl
     ↓
[compiled_claims] → claims/compiled/*.jsonl
```

**相关脚本**：
- [`claimify_all.md`](./scripts/claimify-all.md) — LLM 抽取 claim/entity
- [`compiled_claims.md`](./scripts/compiled-claims.md) — 汇总去重

### 1.4 图谱导出流程

```
claims/compiled/*.jsonl  +  export_*.jsonl
           ↓
  [mem0_to_graph]  ──┐
  [claims_to_graph] ─┤
           ↓         ↓
    graph_nodes/edges JSONL
           ↓
   [graph_to_cypher] → *.cypher
           ↓
[neo4j_apply_cypher] → Neo4j
```

**相关脚本**：
- [`mem0_to_graph.md`](./scripts/mem0-to-graph.md) — mem0 export → graph IR
- [`claims_to_graph.md`](./scripts/claims-to-graph.md) — claims → graph IR
- [`graph_to_cypher.md`](./scripts/graph-to-cypher.md) — graph IR → Cypher
- [`neo4j_apply_cypher.md`](./scripts/neo4j-apply-cypher.md) — Cypher → Neo4j

### 1.5 辅助工具

| 脚本 | 说明 |
|------|------|
| [`latest_file.md`](./scripts/latest-file.md) | 获取最新文件路径（justfile 集成） |
| [`neo4j_clear.md`](./scripts/neo4j-clear.md) | 清空 Neo4j 数据（不重启容器） |
| [`export_node_schema.md`](./scripts/export-node-schema.md) | 导出节点 Schema 参考 |
| [`export_edge_schema.md`](./scripts/export-edge-schema.md) | 导出边 Schema 参考 |

### 1.6 完整执行顺序

```bash
# 1) index
uv run memory_bench/scripts/build_index.py

# 2) annotate
uv run memory_bench/scripts/annotate_all.py --workers 6

# 3) compile
uv run memory_bench/scripts/compile_events.py

# 4) mem0 ingest + export
uv run memory_bench/scripts/replay_mem0.py ingest
uv run memory_bench/scripts/replay_mem0.py export

# 5) claimify + compile claims
latest_export=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0)
uv run memory_bench/scripts/claimify_all.py --input "$latest_export"
uv run memory_bench/scripts/compiled_claims.py --force

# 6) graph → cypher
just memory-item-to-cypher     # mem0 归属图 → Cypher
just claim-items-to-cypher     # claims 语义图 → Cypher

# 7) 导入 Neo4j
just neo4j-apply-cypher
```

> 工作流编排由 `justfile` 管理，详见仓库根目录 `justfile`。

---

## 二、实时管线（Real-time Pipeline）

实时管线用于 Chat Server，在用户对话过程中实时提取 claim 并写入 Neo4j。

### 2.1 架构概览

```
OpenAI 兼容客户端（AIChat 等）
     ↓  POST /memory/v1/chat/completions
proxy_router.py（透明代理）
     ├─ mem0 检索相关记忆 → 注入 system prompt
     ├─ 请求原样透传上游 LLM（stream / tool_call 均支持）
     ├─ 响应返回客户端
     └─ 异步写回 mem0（仅 user + assistant 轮次）
            └─ [可选] 实时图谱写入
                   ├─ claim_extractor → 提取 claim/entity
                   └─ graph_writer → Cypher MERGE → Neo4j
```

主链路（`src/lab`）不经过代理：`MemoryPlugin` 直接调用 `/memory/search` 与 `/memory/add`。

> 历史说明：早期的 `chat_router.py`（`/memory/chat`）与 `conversation_store.py` 已迁移到 `src/lab`（#274）。

### 2.2 核心模块

| 模块 | 说明 |
|------|------|
| `proxy_router.py` | OpenAI 兼容透明代理，`/memory/v1/chat/completions`（详见 [路由与端点](./server/routes)） |
| [`chat_server.md`](./scripts/chat-server.md) | 独立启动器 + CLI |
| [`startup.md`](./scripts/startup.md) | 初始化帮助函数（env 加载、配置解析） |

### 2.3 实时图谱写入

| 模块 | 说明 |
|------|------|
| [`claim_extractor.md`](./scripts/claim-extractor.md) | 实时 claim 提取（LLM-based） |
| [`graph_writer.md`](./scripts/graph-writer.md) | Cypher 生成 + Neo4j 写入 |
| [`neo4j_queries.md`](./scripts/neo4j-queries.md) | Cypher 查询模板（与业务逻辑分离） |

### 2.4 调试工具

| 工具 | 说明 |
|------|------|
| [`chat_cli.md`](./scripts/chat-cli.md) | 终端交互式对话客户端 |

### 2.5 启动方式

```bash
# 启动 Server（user_id / agent_id / agent_name / port）
just memory-chat-server xnne congyin 聪音 8080

# 直接启动（自定义端口）
uv run memory_bench/server/chat_server.py --port 9090

# 启用实时图谱写入
uv run memory_bench/server/chat_server.py --enable-graph

# 启动 CLI 调试客户端
just memory-chat-cli
```

---

## 三、工具模块

这些模块不是独立 CLI，而是被其他脚本复用的工具库。

| 模块 | 说明 |
|------|------|
| [`bench_logger.md`](./scripts/bench-logger.md) | 统一彩色日志 |
| [`rate_limiter.md`](./scripts/rate-limiter.md) | LLM API 令牌桶 + 并发控制 |
| [`tag_registry.md`](./scripts/tag-registry.md) | tag 归一化与候选选择 |

---

## 四、离线管线 vs 实时管线 — 对比

| 维度 | 离线管线 | 实时管线 |
|------|----------|----------|
| **用途** | benchmark replay | 真实用户对话 |
| **中间产物** | 全部持久化（JSONL + Cypher 文件） | 不持久化（内存中直接执行） |
| **Claim 提取** | `claimify_all.py` → 文件 | `claim_extractor.py` → 内存 |
| **图谱构建** | `claims_to_graph.py` → 文件 | `graph_writer.py` → 内存 |
| **Neo4j 写入** | `neo4j_apply_cypher.py` 执行文件 | `graph_writer.py` 直接 `docker exec` |
| **对话存储** | 无（一次性回放） | 无（代理透传，由调用方 / `src/lab` 管理） |

---

## 五、增量检查点总览

| 步骤 | 脚本 | 增量依据 | 跳过条件 |
|------|------|---------|---------|
| 1 | `annotate_all.py` | `data/events/by_chapter/{conv_id}.jsonl` | 文件存在且非空 |
| 2 | `replay_mem0 ingest` | `state/mem0_*.checkpoint.json` | checkpoint 已记录该事件 |
| 3 | `replay_mem0 export` | 无 | 总是导出当前快照 |
| 4 | `claimify_all.py` | `data/claims/by_conv/{conv_id}.jsonl` | by_conv 文件存在 |
| 5 | `compiled_claims.py` | `data/claims/compiled/*.jsonl` | 文件存在且 `--force` 未指定 |
| 6 | `mem0_to_graph.py add` | `state/graphify/state.sqlite` | 已处理的 export 文件跳过 |
| 7 | `graph_to_cypher.py` | 无 | 总是生成新 Cypher |
| 8 | `neo4j_apply_cypher.py` | 无 | MERGE 幂等，重复执行安全 |

---

## 六、快速参考

### 清理命令

| 命令 | 清理范围 |
|------|--------|
| `clean-neo4j` | Neo4j 图数据（Docker volume） |
| `clean-bench-logs` | 整个 `logs/` 目录 |
| `clean-bench-state` | 整个 `state/` 目录 |
| `clean-bench-events` | `data/events/` |
| `clean-bench-claims` | `data/claims/` |
| `clean-realtime` | qdrant_storage + Neo4j（实时管线专用） |

### 常见场景

| 场景 | 命令 |
|------|------|
| 第一次跑通全流程 | `just mem0-run-from-annotate` |
| 调试 ingest/export | `just mem0-run-from-ingest` |
| 调试 claim 提取 | `just mem0-run-from-claim` |
| 测试实时管线 | `just mem0-run-real-time` |

---

## 七、相关文档

- [文档地图](./index.md)
- [节点 Schema](./schema/node.md) — Neo4j 节点 Schema
- [边 Schema](./schema/edge.md) — Neo4j 边 Schema
- [Typing 设计](./typing-design.md) — 类型设计
- [锚点与模板](./schema/anchors.md) — 全链路数据 schema 与样例
