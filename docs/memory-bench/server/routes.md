# 路由与端点

Memory Bench Server 暴露两组 API，挂载在 FastAPI 应用的 `/memory` 前缀下：

```python
app.include_router(memory_router, prefix="/memory")
# /memory/search   ← 记忆检索
# /memory/add      ← 记忆写入 + 图谱管线
# /memory/health   ← 健康检查

app.include_router(proxy_router, prefix="/memory")
# /memory/v1/chat/completions ← OpenAI 兼容透明代理（记忆检索注入 + 异步写回）
# /memory/v1/models           ← 上游模型列表透传
```

本页详述记忆 API（`memory_router`）；代理端点对客户端完全透明（换个 `base_url` 即可接入），行为见 [设计理念](./design)。

---

## `POST /memory/search`

语义检索与某个 `agent_id` 相关的记忆。

**请求格式**：

```json
{
  "query": "用户上次提到了什么",
  "user_id": "xnne",
  "agent_id": "elaina",
  "limit": 5
}
```

| 字段 | 必填 | 说明 |
|------|:---:|------|
| `query` | ✅ | 检索用的语义查询文本 |
| `user_id` | ❌ | mem0 用户 ID，不传则使用 server 启动时配置的默认值 |
| `agent_id` | ❌ | mem0 Agent ID，不传则使用 server 启动时配置的默认值 |
| `limit` | ❌ | 返回结果数量上限，默认使用 server 配置的 `search_limit` |

**响应格式**：

```json
{
  "results": [
    {
      "id": "abc123",
      "memory": "[Agent] 用户喜欢喝咖啡",
      "score": 0.87
    }
  ],
  "count": 1
}
```

**调用方**：`MemoryPlugin.on_before_turn()`，在每轮对话前搜索相关记忆注入 context。

---

## `POST /memory/add`

写入一轮对话到 mem0，并异步触发 Neo4j 图谱管线。

**请求格式**：

```json
{
  "user_text": "你还记得我喜欢喝什么吗",
  "assistant_text": "记得，你喜欢喝咖啡～",
  "user_id": "xnne",
  "agent_id": "elaina"
}
```

| 字段 | 必填 | 说明 |
|------|:---:|------|
| `user_text` | ✅ | 本轮用户消息 |
| `assistant_text` | ✅ | 本轮 assistant 回复（完整收齐后再传） |
| `user_id` | ✅ | mem0 用户 ID |
| `agent_id` | ✅ | mem0 Agent ID，决定记忆写入哪个 agent 的命名空间 |

**响应格式**：

```json
{
  "status": "queued"
}
```

写入是**异步**的——接口立即返回 `queued`，mem0 写入和图谱管线在后台执行，不阻塞 AgentCore 的主流程。

**后台处理流程**：

```
mem0.add(user_text + assistant_text, user_id, agent_id)
  ↓
提取新增记忆结果
  ↓
claim_extractor → LLM 提取 claim / entity
  ↓
neo4j_queries → Cypher MERGE → MemoryItem 节点写入 Neo4j
```

> [!NOTE] 认证：通过 `CHAT_SERVER_API_KEY` 环境变量启用 Bearer token 认证。未配置时无需认证。

**调用方**：`MemoryPlugin.on_after_turn()`，在每轮 `run_turn()` 结束、`assistant_text` 完整收齐后调用。

---

## `GET /memory/health`

健康检查端点。

**响应格式**：

```json
{
  "status": "ok",
  "mem0_ready": true,
  "llm_ready": true,
  "model": "google/gemini-2.0-flash",
  "graph_pipeline_enabled": true,
  "claim_llm_model": "google/gemini-2.0-flash"
}
```

---

## 🚀 启动配置

### 环境变量（`.env.benchmark`）

```bash
# mem0 identity（REQUIRED - 无 fallback）
CHAT_USER_ID=""
CHAT_AGENT_ID=""

# Agent metadata（REQUIRED - 写入 Neo4j 图谱节点）
METADATA_USER_ID=""
METADATA_USER_NAME=""
METADATA_AGENT_ID=""
METADATA_AGENT_NAME=""
METADATA_CHARACTER_ID=""
METADATA_CHARACTER_NAME=""

# Chat LLM
CHAT_API_KEY=sk-xxx
CHAT_BASE_URL=https://openrouter.ai/api/v1
CHAT_MODEL=google/gemini-2.0-flash

# mem0 LLM（默认复用 Chat LLM）
MEM0_LLM_API_KEY=
MEM0_LLM_BASE_URL=
MEM0_LLM_MODEL=

# Local embedding
LOCAL_EMBEDDING_BASE_URL=http://localhost:12395/v1
LOCAL_EMBEDDING_MODEL=bge-m3

# 认证（可选）
CHAT_SERVER_API_KEY=your-secret-key

# 图谱管线（可选）
ENABLE_GRAPH=true
CLAIM_LLM_API_KEY=
CLAIM_LLM_BASE_URL=
CLAIM_LLM_MODEL=
NEO4J_CONTAINER=membench-neo4j-mem0
```

### 作为 lab server 的内嵌服务启动

主链路下，memory_bench 由 `src/lab/server.py` 在启动时自动挂载，不需要单独启动进程：

```toml
# lab.toml
[package]
memory_bench = true

[memory_bench]
search_limit = 10
server_api_key = ""  # 可选
```

### 作为独立调试工具启动（chat_server）

用于直接与特定 `agent_id` 的记忆对话，测试记忆内容或验证图谱写入：

```bash
# 格式：just memory-chat-server <user_id> <agent_id> <agent_name> [port]
just memory-chat-server xnne congyin 聪音 8080
just memory-chat-server xnne elaina 伊蕾娜 8081
```

---

## 📚 延伸阅读

- [设计理念](./design) — 架构决策与 Agent 关系
