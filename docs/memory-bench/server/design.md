# 设计理念

Memory Bench Server 是 memory_bench 子项目的核心服务，为 AI 角色对话提供**记忆增强**能力。

## 🎯 核心问题

> AI 聊天机器人普遍存在"金鱼记忆"问题——每次对话都从零开始，不记得之前说过什么。

Memory Bench Server 的目标是解决这个问题：让 AI 角色能**真正记住**与用户的交互，并将记忆结构化为可查询的知识图谱。

---

## 📐 架构定位：记忆后端，不是透明代理

Memory Bench Server 是一个**记忆后端服务**，职责是存储、检索记忆，以及维护 Neo4j 知识图谱。它不参与 LLM 调用，也不管理对话历史——这些由 `AgentCore` 负责。

```
AgentCore（主链路）
  │
  ├── on_before_turn → POST /memory/search   ← 搜索相关记忆，注入 context
  │
  ├── run_turn() → LLM 生成回复
  │
  └── on_after_turn → POST /memory/add      ← 写入本轮对话，触发图谱管线
```

调用方永远是 `MemoryPlugin`（AgentCore 的 hook 插件），identity（`user_id`/`agent_id`）由 Profile 的 `[plugins.memory]` 决定，server 端不持有固定 identity。

---

## 🧠 记忆架构

### mem0：记忆的存储与检索

[mem0](https://github.com/mem0ai/mem0) 负责从对话中**自动提取**和**语义检索**记忆：

```
POST /memory/add（user_text + assistant_text + user_id + agent_id）
  ↓
mem0.add() → 自动提取记忆要点 → 存入 Qdrant
  ↓
claim_extractor.py → LLM 提取 claim / entity
  ↓
graph_writer.py → Cypher MERGE → Neo4j
```

```
POST /memory/search（query + user_id + agent_id）
  ↓
mem0.search() → 语义检索 → 返回相关记忆列表
```

**关键设计决策**：
- 写入只记录 `user_text` + `assistant_text`，不写入工具调用中间步骤
- 事实提取使用自定义 prompt，区分 `[User]` 和 `[Agent]` 前缀
- `user_id` / `agent_id` 来自请求参数，server 端不 fallback——缺失直接报错

### Neo4j：记忆的图谱化

每条记忆通过实时图谱管线被结构化为知识图谱节点：

```
mem0.add() 返回结果
  ↓
claim_extractor.py → 提取 claim / entity
  ↓
neo4j_queries.py → Cypher MERGE 写入 Neo4j
  ↓
MemoryItem 节点 → 关联 Character / Scene / Conversation
```

> [!TIP] 图谱管线是可选的（`--enable-graph`），不影响基础搜索和写入功能。

### 多 Agent 共存

不同 Agent（如 elaina、congyin）共用同一个 Neo4j 图，通过 `agent_id` 隔离各自的记忆节点。mem0 的向量搜索以 `(user_id, agent_id)` 为命名空间，天然隔离。

```
Neo4j 图
  ├── (char:elaina) ← elaina 的 MemoryItem 节点
  ├── (char:congyin) ← congyin 的 MemoryItem 节点
  └── (char:xnne) ← 用户节点，与两个 agent 均有关联边
```

---

## 🔌 与 `src/lab` 的关系

`src/lab`（主项目）通过 `MemoryPlugin` 与 Memory Bench Server 交互：

```
Profile（elaina.toml / congyin.toml）
  [plugins.memory]
    user_id = "xnne"
    agent_id = "elaina"      ← 记忆归属的唯一来源
    base_url = "http://localhost:12393"

AgentCore
  ├── MemoryPlugin.on_before_turn → /memory/search（带 agent_id）
  └── MemoryPlugin.on_after_turn  → /memory/add（带 agent_id）
```

**约定**：
- Memory Bench Server 只做记忆存取，不感知 AgentCore 的 LLM 调用或工具调用
- `agent_id` 由 Plugin 从 Profile 读取后显式传入，server 不持有默认值
- 配置隔离：memory_bench 的连接配置来自 `.env.benchmark`，不读取 `lab.toml`

---

## 🛠️ chat_server：独立调试工具

`chat_server.py` 是一个**独立的命令行调试工具**，不在主链路中。它直接起一个带记忆的 REPL 对话，用于测试特定 `agent_id` 的记忆内容，或在不启动完整 `src/lab` 的情况下验证 memory_bench 的功能。

```bash
just memory-chat-server xnne congyin 聪音 8080
just memory-chat-server xnne elaina 伊蕾娜 8081
```

主链路（elaina VTuber / congyin /memory/chat）不经过 chat_server，而是通过 AgentCore + MemoryPlugin 直接调用 `/memory/search` 和 `/memory/add`。

---

## 📁 代码结构

```
memory_bench/server/
├── chat_server.py          # 独立调试工具（CLI + REPL，非主链路）
├── chat_cli.py             # REPL 实现
├── startup.py              # 初始化逻辑（mem0 / OpenAI / 图谱管线）
├── router.py               # FastAPI 路由（/search、/add、/health）
├── proxy_router.py         # OpenAI 兼容透明代理（/v1/chat/completions、/v1/models）
├── claim_extractor.py      # LLM Claim 提取
├── graph_writer.py         # 实时图谱写入（Cypher MERGE）
└── neo4j_queries.py        # Cypher 语句模板与写入逻辑
```

---

## 📚 延伸阅读

- [路由与端点](./routes) — API 文档
