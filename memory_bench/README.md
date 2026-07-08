# memory_bench

`memory_bench` 是仓库内的独立模块，用于承载"记忆基准（Memory Bench）"相关的：

- 原始章节语料（`memory_bench/data/source/raw/`）
- 规范化章节语料（`memory_bench/data/source/norm/`，可选）
- 机器可读索引（`memory_bench/data/source/index.json`）
- 运行时 prompt 资产与生成的 schema 参考（`memory_bench/docs/`）
- 工作流脚本（`memory_bench/scripts/`）

> 工作流文档（脚本指南、schema 说明、server 设计等）在 VitePress 站点：[docs/memory-bench](../docs/memory-bench/)。
- 标注产物、回放状态与调试日志（运行后生成在 `memory_bench/data/*`、`memory_bench/logs/*`、`memory_bench/state/*`）

本模块目标是：让从"章节原文"到"可重放事件流"、再到"Mem0 检索日志/记忆快照"、再到"Claim/Entity 图谱旁路产物"，整个链路 **可复现、可审查、可对照**。

---

## 目录结构（核心）

```text
memory_bench/
├─ README.md
├─ docs/                    (运行时资产，非文档站内容)
│  ├─ 06_NODE_SCHEMA_REFERENCE.md   (export_node_schema.py 生成)
│  ├─ 08_EDGE_SCHEMA_REFERENCE.md   (export_edge_schema.py 生成)
│  ├─ 20_ANNOTATOR_PROMPT.md        (annotate_all.py 运行时加载)
│  ├─ 21_SCENE_CANON.md
│  ├─ 22_PERSONA_CANON.md           (chat_cli.py 运行时加载)
│  └─ 23_CLAIM_EXTRACTOR_PROMPT.md  (claimify_all.py 运行时加载)
├─ scripts/
│  ├─ build_index.py
│  ├─ annotate_all.py
│  ├─ compile_events.py
│  ├─ replay_mem0.py
│  ├─ claimify_all.py
│  ├─ compiled_claims.py
│  ├─ mem0_to_graph.py
│  ├─ claims_to_graph.py
│  ├─ graph_to_cypher.py
│  ├─ neo4j_apply_cypher.py
│  ├─ neo4j_clear.py       (清空 Neo4j，不重启容器)
│  ├─ export_node_schema.py     (导出 Neo4j Schema 参考文档)
│  ├─ export_edge_schema.py (导出 Neo4j 边 Schema 参考文档)
│  ├─ latest_file.py
│  ├─ bench_logger.py      (工具模块)
│  ├─ tag_registry.py      (工具模块)
│  └─ rate_limiter.py      (工具模块)
├─ server/
│  ├─ __init__.py
│  ├─ router.py              (mem0 原生记忆 API — `/memory/search`、`/memory/add`、`/memory/health`)
│  ├─ proxy_router.py        (OpenAI 兼容代理 — `/memory/v1/chat/completions`、`/memory/v1/models`)
│  ├─ neo4j_queries.py       (Neo4j Cypher 查询模板)
│  ├─ startup.py             (初始化帮助函数 — 供外部 host app 调用)
│  ├─ chat_server.py         (独立启动器 + CLI)
│  ├─ chat_cli.py            (终端对话调试客户端)
│  ├─ claim_extractor.py     (实时 claim/entity 提取)
│  └─ graph_writer.py        (实时图谱写入 Neo4j)
├─ resources/
│  └─ tag_registry.json
├─ data/
│  ├─ source/
│  │  ├─ index.json
│  │  ├─ raw/   (chXX_*.md)
│  │  └─ norm/  (chXX_*.norm.md, optional)
│  ├─ events/
│  │  ├─ by_chapter/ (chXX.jsonl)
│  │  └─ compiled/   (all.jsonl)
│  └─ claims/
│     ├─ by_conv/    (chXX.jsonl)
│     └─ compiled/   (entities.jsonl / claims.jsonl / compiled_meta.json)
├─ logs/
│  ├─ annotate_prompt/   (per chapter)
│  ├─ annotate_raw/      (per chapter)
│  ├─ annotate_meta/     (per chapter)
│  ├─ replay_mem0/       (probe/export logs)
│  ├─ claimify_prompt/   (per conv + chunk)
│  ├─ claimify_raw/      (per conv + chunk)
│  └─ claimify_meta/     (per conv)
└─ state/
   ├─ mem0_*.checkpoint.json
   └─ qdrant_storage/...
```

---

## 通用运行方式（推荐）

在仓库根目录执行：

```bash
uv run memory_bench/scripts/<script>.py -h
```

> **注意：** 统一使用 `uv run memory_bench/scripts/xxx.py` 的方式调用，不推荐 `uv run python -m` 方式。

---

## 环境变量与配置（bench 专用）

多数脚本会尝试读取：

- `memory_bench/.env.benchmark`

### 必要变量（标注/抽取/回放会用到）

LLM 和 Embedding 的 API Key / Base URL 独立配置，允许使用不同的服务提供商或代理。

**Chat / LLM：**

- `BENCHMARK_LLM_API_KEY`
- `BENCHMARK_LLM_BASE_URL`（OpenAI 兼容接口）
- `BENCHMARK_LLM_MODEL`

**Embedding（仅 `replay_mem0.py` 必需）：**

- `LOCAL_EMBEDDING_BASE_URL`（可选，默认 `http://localhost:12395/v1`）
- `LOCAL_EMBEDDING_MODEL`（可选，默认 `bge-m3`）

**可选：**

- `BENCHMARK_LLM_RATE_LIMIT`（每分钟最大 LLM 调用次数，0 = 不限制）

> `annotate_all.py` / `claimify_all.py` 只需要 `BENCHMARK_LLM_*` 三项；
> `replay_mem0.py` 会强制检查六项都存在（LLM + Embedding 都要）。

---

## 一套可复制的完整流程

### A. 从章节原文 → 事件 JSONL → Mem0 回放/导出

```bash
# 1) 构建章节索引
uv run memory_bench/scripts/build_index.py

# 2) 批量标注为 events（建议先小范围试跑）
uv run memory_bench/scripts/annotate_all.py --only ch01 --workers 1
uv run memory_bench/scripts/annotate_all.py --workers 6

# 3) 按 index 顺序拼接成单一 all.jsonl
uv run memory_bench/scripts/compile_events.py

# 4) 回放写入 Mem0（默认跳过 filler，且不会把 probe 写入记忆）
uv run memory_bench/scripts/replay_mem0.py ingest

# 5) 导出 Mem0 当前快照（供 claimify / graph 使用）
uv run memory_bench/scripts/replay_mem0.py export

# 可选：基于事件文本推断 owner（默认开启）
uv run memory_bench/scripts/replay_mem0.py export \
  --events memory_bench/data/events/compiled/all.jsonl \
  --infer-owner \
  --owner-fallback Agent
```

产物重点看：

- `memory_bench/data/events/by_chapter/*.jsonl`
- `memory_bench/data/events/compiled/all.jsonl`
- `memory_bench/logs/replay_mem0/export_*.jsonl`
- `memory_bench/logs/replay_mem0/probe_*.jsonl`

---

### B. 从 Mem0 export → Claim/Entity JSONL → 全局编译（去重汇总）

```bash
# 6) 从 export 快照抽取 claim/entity（按 conv_id 分组；内部会按 chunk 调 LLM）
uv run memory_bench/scripts/claimify_all.py \
  --input memory_bench/logs/replay_mem0/export_YYYYMMDD_HHMMSS.jsonl
```

说明：
- `claimify_all.py` 会维护一个 Tag 归一化/复用用的注册表：
  `memory_bench/resources/tag_registry.json`
- 该文件用于向 LLM 提供 TopK 候选 canonical tags，减少近义重复 Tag。
- 初始可为空；首次运行后会自动写入/更新。

```bash
# 7) 汇总 by_conv 到全局 compiled（Neo4j 友好）
uv run memory_bench/scripts/compiled_claims.py --force
```

产物重点看：

- `memory_bench/data/claims/by_conv/*.jsonl`
- `memory_bench/data/claims/compiled/entities.jsonl`
- `memory_bench/data/claims/compiled/claims.jsonl`
- `memory_bench/data/claims/compiled/compiled_meta.json`

---

### C. Graph IR → Neo4j Cypher → 导入 Neo4j

图谱导出分两条线：
- **Mem0 归属图**（MemoryItem / Character / Agent 等元数据关系）→ `mem0_to_graph.py`
- **Claims 语义图**（Claim / Entity / Tag 等语义关系）→ `claims_to_graph.py`

两者产出统一的 Graph IR（nodes/edges JSONL），下游共用 `graph_to_cypher.py` 生成 Cypher。

```bash
# 8a) Mem0 归属图
latest_export=$(uv run memory_bench/scripts/latest_file.py \
  --export-dir memory_bench/logs/replay_mem0 --glob "export_*.jsonl")
uv run memory_bench/scripts/mem0_to_graph.py add \
  --input "$latest_export" \
  --out-dir memory_bench/logs/replay_mem0/graphify

# 8b) Claims 语义图
uv run memory_bench/scripts/claims_to_graph.py \
  --nodes-dir memory_bench/data/claims/compiled \
  --out-dir memory_bench/logs/claims/graphify

# 9) Graph IR → Cypher
mem0_nodes=$(uv run memory_bench/scripts/latest_file.py \
  --export-dir memory_bench/logs/replay_mem0/graphify --glob "*nodes*.jsonl")
mem0_edges=$(uv run memory_bench/scripts/latest_file.py \
  --export-dir memory_bench/logs/replay_mem0/graphify --glob "*edges*.jsonl")
uv run memory_bench/scripts/graph_to_cypher.py \
  --nodes "$mem0_nodes" --edges "$mem0_edges" \
  --out-dir memory_bench/logs/replay_mem0/graphify/neo4j

# 10) 导入 Neo4j
uv run memory_bench/scripts/neo4j_apply_cypher.py mem0 \
  memory_bench/logs/replay_mem0/graphify/neo4j graph
```

> 也可以通过 justfile recipes 一键执行，详见 `just --list` 中 `mem0-to-graph` / `mem0-graph-to-cypher` 等。

---

## 脚本简表

| 脚本 | 作用 |
|------|------|
| `build_index.py` | raw/norm 扫描 → `data/source/index.json` |
| `annotate_all.py` | 章节文本 → 严格 JSONL events（by_chapter + 调试日志） |
| `compile_events.py` | 按 index 顺序拼接 → `events/compiled/all.jsonl` |
| `replay_mem0.py` | ingest/probe/export（本地 qdrant 持久化 + checkpoint） |
| `claimify_all.py` | mem0 export → claim/entity JSONL（by_conv + chunk 日志）+ tag registry |
| `compiled_claims.py` | by_conv 汇总去重 → compiled entities/claims |
| `mem0_to_graph.py` | mem0 export → Graph IR nodes/edges（归属图） |
| `claims_to_graph.py` | claims compiled → Graph IR nodes/edges（语义图） |
| `graph_to_cypher.py` | Graph IR → Neo4j Cypher 脚本 |
| `neo4j_apply_cypher.py` | 将 Cypher 导入指定 Neo4j docker 容器 |
| `neo4j_clear.py` | 清空 Neo4j 图数据（不重启容器） |
| `latest_file.py` | 获取目录下按 glob 匹配的最新文件路径 |
| `bench_logger.py` | 统一日志工具模块 |
| `tag_registry.py` | Tag 归一化注册表工具模块 |
| `rate_limiter.py` | LLM API 令牌桶限速工具模块 |
| `chat_cli.py` | 终端对话调试客户端（HTTP REPL，自动加载 persona） |
| `claim_extractor.py` | 实时 claim/entity 提取（`claimify_all.py` 的实时对应物，被 router.py 调用） |
| `graph_writer.py` | 实时图谱写入（claim records → Graph IR → Cypher → Neo4j MERGE） |
| `startup.py` | 初始化帮助函数（`load_memory_bench_env` / `resolve_memory_bench_config` / `init_router_state`），供外部 FastAPI host app 挂载 router 时调用 |

---

## `index.json` 格式（供 annotate/compile 消费）

```json
[
  {
    "id": "ch01",
    "raw_path": "memory_bench/data/source/raw/ch01_xxx.md",
    "norm_path": "memory_bench/data/source/norm/ch01_xxx.norm.md"
  }
]
```

- `id`：章节 ID（`chXX`）
- `raw_path`：相对仓库根目录路径（必有）
- `norm_path`：相对仓库根目录路径（可为空字符串）

---

## `dashboard.json`（Neo4j Browser 仪表盘配置）

仓库提供了现成的 Neo4j Browser 仪表盘配置文件：

- `memory_bench/dashboard.json`

该文件用于快速加载一个「full-graph」页面，内置 `MATCH p=()--() RETURN p;` 图查询，并为 `Node`、`MemoryItem`、`Claim`、`Agent`、`Domain`、`Tag` 等标签预设展示字段与 schema 元数据，便于对 mem0 + claims 全图进行可视化巡检。

---

## 依赖安装（memory_bench 组）

如需安装 bench 相关依赖（含 mem0ai 等）：

```bash
uv sync --group memory_bench
```

---

## Done 校验建议（最少检查）

- `build_index.py` 后：`memory_bench/data/source/index.json` 存在且可解析
- `annotate_all.py` 后：`data/events/by_chapter/chXX.jsonl` 存在，且 `logs/annotate_meta/chXX.json` 无失败
- `compile_events.py` 后：`data/events/compiled/all.jsonl` 存在且拼接成功
- `replay_mem0.py export` 后：`logs/replay_mem0/export_*.jsonl` 有内容
- `claimify_all.py` 后：`data/claims/by_conv/chXX.jsonl` 存在
- `compiled_claims.py` 后：`data/claims/compiled/*.jsonl` + `compiled_meta.json` 存在
- `mem0_to_graph.py` + `graph_to_cypher.py` 后：`*nodes*.jsonl`、`*edges*.jsonl`、`neo4j/*.cypher` 存在

---

## Memory Chat Server（`memory_bench/server/`）

### 概述

`memory_bench/server/` 提供两个 FastAPI router，用于不同场景：

1. **`proxy_router.py`** — OpenAI 兼容的透明代理（`/memory/v1/chat/completions`），转发到上游 LLM 并旁路做记忆检索/写入
2. **`router.py`** — mem0 原生记忆 API（`/memory/search`、`/memory/add`），供主服务的 `memory` 插件（`src/lab/plugins/memory/`）调用

> 历史说明：早期的 `chat_router.py`（`/memory/chat`）与 `conversation_store.py` 已在 [#274](https://github.com/XnneHangLab/XnneHangLab/issues/274) 迁移到 `src/lab`，对话执行逻辑不再属于 memory_bench。

### 文件说明

| 文件 | 作用 |
|------|------|
| `startup.py` | 初始化帮助函数（`load_memory_bench_env` / `resolve_memory_bench_config` / `init_router_state`），供外部 host app 共用 |
| `proxy_router.py` | OpenAI 兼容 router，端点：`/memory/v1/chat/completions`、`/memory/v1/models`、`/memory/health` |
| `router.py` | 记忆 API router，端点：`/memory/search`、`/memory/add`、`/memory/health` |
| `chat_server.py` | 独立启动器 + CLI，组装 proxy_router + router 并启动 uvicorn |
| `chat_cli.py` | 终端对话调试客户端，通过 HTTP 调用 server（自动加载 `docs/22_PERSONA_CANON.md`） |
| `claim_extractor.py` | 实时 claim/entity 提取（LLM-based） |
| `graph_writer.py` | 实时图谱写入 Neo4j（Cypher MERGE） |
| `neo4j_queries.py` | Neo4j Cypher 查询模板（与业务逻辑分离） |

### 启动方式

**独立启动（推荐测试用）：**

```bash
# 通过 justfile（user_id / agent_id / agent_name / port）
just memory-chat-server xnne congyin 聪音 8080

# 直接调用
uv run memory_bench/server/chat_server.py --port 8080
```

**挂载到 lab server：**

在 `config/lab.toml` 中开启：

```toml
[package]
memory_bench = true
```

lab server 启动时会自动初始化 mem0 并挂载 router：
- `proxy_router.py` → `/memory/v1/chat/completions`、`/memory/v1/models`
- `router.py` → `/memory/search`、`/memory/add`、`/memory/health`

### 环境变量

配置通过 `memory_bench/.env.benchmark` 加载：

```bash
# Chat LLM 配置
CHAT_API_KEY=sk-xxx
CHAT_BASE_URL=https://api.openai.com/v1
CHAT_MODEL=gpt-4o-mini

# Server 鉴权（可选）
CHAT_SERVER_API_KEY=your-secret-key

# 实时图谱写入（可选）
ENABLE_GRAPH=true
NEO4J_CONTAINER=membench-neo4j-mem0
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4jneo4j
```

### 使用场景对比

| 场景 | 推荐入口 | 理由 |
|------|------------|------|
| OpenAI 兼容客户端直连（AIChat 等） | `proxy_router.py` | 协议兼容，记忆检索/写入对客户端透明 |
| 主服务 memory 插件检索/写入 | `router.py` | `/memory/search` + `/memory/add` 原生 API |
| 快速测试/调试 | `chat_cli.py` | 终端 HTTP REPL，自动加载 persona |

