# 实时管线 Neo4j 图谱边 Schema 参考

> **用途**：记录实时管线（memory-chat-server）的 Neo4j 图谱边 Schema，确保与离线管线完全兼容。
> 
> **生成方式**：本文档基于实时管线的代码逻辑生成，可与离线管线的 `08_EDGE_SCHEMA_REFERENCE.md` 对比验证。

---

> **实现入口说明（2026-02 更新）**：实时写入入口在 `router.create_memory_item_node_v2()`，由它调用
> `neo4j_queries.create_conversation_cypher()` 与 `neo4j_queries.create_memory_item_cypher()` 生成 Cypher。
> 为避免 schema 漂移，不应在 router 中维护独立的内联关系创建语句。

## 边类型（Edge Types）

实时管线支持以下边类型（按创建方式分类）：

| 边类型 | 源节点类型 | 目标节点类型 | 创建方式 | 说明 |
|---------|-----------|-------------|----------|------|
| `ACTOR` | Agent | Character | `neo4j_queries.create_metadata_nodes_cypher()` | Agent 扮演 Character |
| `ACTOR` | User | Character | `neo4j_queries.create_metadata_nodes_cypher()` | User 扮演 Character |
| `IN_SCENE` | Character | Scene | `neo4j_queries.create_metadata_nodes_cypher()` | Character 在 Scene 中 |
| `OWNS_MEMORY` | Character | MemoryItem | `neo4j_queries.create_memory_item_cypher()` | Character 拥有 MemoryItem |
| `IN_SCENE` | MemoryItem | Scene | `neo4j_queries.create_memory_item_cypher()` | MemoryItem 属于 Scene |
| `HAS_CHARACTER` | MemoryItem | Character | `neo4j_queries.create_memory_item_cypher()` | MemoryItem 关联 Character |
| `FROM_CONV` | MemoryItem | Conversation | `neo4j_queries.create_memory_item_cypher()` | MemoryItem 来自 Conversation |
| `CONV_IN_SCENE` | Conversation | Scene | `neo4j_queries.create_memory_item_cypher()` | Conversation 在 Scene 中 |
| `CONV_HAS_CHARACTER` | Conversation | Character | `neo4j_queries.create_memory_item_cypher()` | Conversation 关联 Character |

---

## 边属性（Edge Properties）

### ACTOR (agent:congyin → char:congyin)

```json
{
  "processed_key": "metadata_2026-02-28T07:05:18Z",
  "source_point_id": "metadata",
  "exported_at": "2026-02-28T07:05:18Z",
  "created_at": "2026-02-28T07:05:18Z",
  "id": "edge:ACTOR:agent:congyin:char:congyin",
  "type": "ACTOR",
  "src": "agent:congyin",
  "dst": "char:congyin"
}
```

**说明**：
- `processed_key`: 处理键（metadata + 时间戳）
- `source_point_id`: 源点 ID（"metadata"）
- `exported_at`: 导出时间（ISO 8601）
- `created_at`: 创建时间（ISO 8601）
- `id`: 边 ID（格式：`edge:{type}:{src}:{dst}`）
- `type`: 边类型
- `src`: 源节点 ID
- `dst`: 目标节点 ID

### OWNS_MEMORY (char:xnne → mem:xxx)

```json
{
  "processed_key": "8eeee526ba66c7c0259fe721a756e709",
  "source_point_id": "2993cc12-65e5-4beb-826e-e8398c87741f",
  "exported_at": "2026-02-28T07:05:02Z",
  "created_at": "2026-02-27T23:04:58.662893-08:00",
  "id": "edge:OWNS_MEMORY:char:xnne:mem:8eeee526ba66c7c0259fe721a756e709",
  "type": "OWNS_MEMORY",
  "src": "char:xnne",
  "dst": "mem:8eeee526ba66c7c0259fe721a756e709"
}
```

**说明**：
- `processed_key`: 处理键（MemoryItem 的 hash）
- `source_point_id`: 源点 ID（mem0 返回的 UUID）
- `exported_at`: 导出时间（ISO 8601）
- `created_at`: 创建时间（ISO 8601）

### IN_SCENE (mem:xxx → scene:chill_ai_chat)

```json
{
  "processed_key": "8eeee526ba66c7c0259fe721a756e709",
  "source_point_id": "2993cc12-65e5-4beb-826e-e8398c87741f",
  "exported_at": "2026-02-28T07:05:02Z",
  "created_at": "2026-02-27T23:04:58.662893-08:00",
  "id": "edge:IN_SCENE:mem:8eeee526ba66c7c0259fe721a756e709:scene:chill_ai_chat",
  "type": "IN_SCENE",
  "src": "mem:8eeee526ba66c7c0259fe721a756e709",
  "dst": "scene:chill_ai_chat"
}
```

### HAS_CHARACTER (mem:xxx → char:xnne)

```json
{
  "processed_key": "8eeee526ba66c7c0259fe721a756e709",
  "source_point_id": "2993cc12-65e5-4beb-826e-e8398c87741f",
  "exported_at": "2026-02-28T07:05:02Z",
  "created_at": "2026-02-27T23:04:58.662893-08:00",
  "id": "edge:HAS_CHARACTER:mem:8eeee526ba66c7c0259fe721a756e709:char:xnne",
  "type": "HAS_CHARACTER",
  "src": "mem:8eeee526ba66c7c0259fe721a756e709",
  "dst": "char:xnne"
}
```

### FROM_CONV (mem:xxx → conv:2026-02-27)

```json
{
  "processed_key": "8eeee526ba66c7c0259fe721a756e709",
  "source_point_id": "2993cc12-65e5-4beb-826e-e8398c87741f",
  "exported_at": "2026-02-28T07:05:02Z",
  "created_at": "2026-02-27T23:04:58.662893-08:00",
  "id": "edge:FROM_CONV:mem:8eeee526ba66c7c0259fe721a756e709:conv:2026-02-27",
  "type": "FROM_CONV",
  "src": "mem:8eeee526ba66c7c0259fe721a756e709",
  "dst": "conv:2026-02-27"
}
```

### CONV_IN_SCENE (conv:2026-02-27 → scene:chill_ai_chat)

```json
{
  "processed_key": "metadata_2026-02-28T07:05:18Z",
  "source_point_id": "metadata",
  "exported_at": "2026-02-28T07:05:18Z",
  "created_at": "2026-02-28T07:05:18Z",
  "id": "edge:CONV_IN_SCENE:conv:2026-02-27:scene:chill_ai_chat",
  "type": "CONV_IN_SCENE",
  "src": "conv:2026-02-27",
  "dst": "scene:chill_ai_chat"
}
```

### CONV_HAS_CHARACTER (conv:2026-02-27 → char:xnne)

```json
{
  "processed_key": "metadata_2026-02-28T07:05:18Z",
  "source_point_id": "metadata",
  "exported_at": "2026-02-28T07:05:18Z",
  "created_at": "2026-02-28T07:05:18Z",
  "id": "edge:CONV_HAS_CHARACTER:conv:2026-02-27:char:xnne",
  "type": "CONV_HAS_CHARACTER",
  "src": "conv:2026-02-27",
  "dst": "char:xnne"
}
```

---

## 与离线管线的兼容性

### ✅ 完全兼容的部分

1. **边 ID 格式**：所有边类型的前缀一致（`edge:{type}:{src}:{dst}`）
2. **边类型**：实时管线的 7 种边类型都包含在离线管线的 12 种中
3. **边方向**：所有边的方向一致
4. **基础属性**：`id`, `type`, `src`, `dst`, `created_at`, `exported_at` 完全一致

### ⚠️ 需要注意的差异

1. **边类型数量**：
   - 离线管线：12 种（ABOUT, ACTOR, CONV_HAS_CHARACTER, CONV_IN_SCENE, EVIDENCED_BY, FROM_CONV, HAS_CHARACTER, HAS_CLAIM, HAS_DOMAIN, HAS_PREDICATE, IN_SCENE, OWNS_MEMORY）
   - 实时管线：7 种（ACTOR, IN_SCENE, OWNS_MEMORY, HAS_CHARACTER, FROM_CONV, CONV_IN_SCENE, CONV_HAS_CHARACTER）
   - **实时管线没有**：HAS_DOMAIN, HAS_PREDICATE, HAS_CLAIM, ABOUT, EVIDENCED_BY
   - **原因**：这些边来自 graph_writer，需要 claim_extractor 输出 claim/entity

2. **边属性**：
   - 离线管线：有 `props_json`（完整 JSON 备份）+ 独立字段
   - 实时管线：有 `processed_key`, `source_point_id`, `exported_at`, `created_at`
   - **影响**：无，核心属性一致

3. **Conversation ID 格式**：
   - 离线管线：`conv:ch00`, `conv:ch01`（按章节）
   - 实时管线：`conv:2026-02-27`, `conv:2026-02-28`（按日期）
   - **影响**：无，两者可以共存

### 🔧 确保兼容性的关键代码

**实时管线**（`neo4j_queries.py`）：
```python
# 边 ID 格式：edge:{type}:{src}:{dst}
edges_map[f"edge:ACTOR:{agent_id}:{agent_char_id}"] = {
    "id": f"edge:ACTOR:{agent_id}:{agent_char_id}",
    "type": "ACTOR",
    "src": agent_id,
    "dst": agent_char_id,
    "props": metadata_provenance,
}
```

**离线管线**（`graph_to_cypher.py`）：
```python
# 完全一致的边 ID 格式
edge_id = f"edge:{edge_type}:{src}:{dst}"
```

---

## 验证方法

### 1. 导出离线管线边 Schema

```bash
uv run memory_bench/scripts/export_edge_schema.py --output /tmp/offline_edges.md
```

### 2. 验证实时管线边 Schema

```bash
# 检查 Neo4j 中的边
MATCH ()-[r]->()
RETURN type(r) AS edge_type, count(*) AS count
ORDER BY edge_type;
```

### 3. 对比两者

```bash
diff /tmp/offline_edges.md docs/memory-bench/schema/realtime-edge.md
```

**预期差异**：
- 边类型数量不同（离线 12 种 vs 实时 7 种）
- Conversation ID 格式不同（`conv:ch00` vs `conv:2026-02-27`）

**不应有的差异**：
- 边类型名称不同
- 边方向不同
- 核心属性（id, type, src, dst）格式不同

---

## 使用场景

1. **验证兼容性**：确保离线/实时管线可以写入同一张图
2. **调试数据问题**：检查实时管线的边是否符合预期
3. **文档参考**：为开发者提供实时管线的完整边 Schema 说明
4. **迁移验证**：从离线管线切换到实时管线时，确保数据一致性

---

## 实时管线边统计

**总计**：7 种边类型

| 边类型 | 数量 | 创建时机 |
|---------|------|---------|
| `ACTOR` | 2 | server 启动时（init_metadata_nodes） |
| `IN_SCENE` | 2 | server 启动时 + MemoryItem 创建时 |
| `OWNS_MEMORY` | N | MemoryItem 创建时 |
| `HAS_CHARACTER` | N | MemoryItem 创建时 |
| `FROM_CONV` | N | MemoryItem 创建时 |
| `CONV_IN_SCENE` | N | MemoryItem 创建时 |
| `CONV_HAS_CHARACTER` | N | MemoryItem 创建时 |

**说明**：
- `N` = 每个 MemoryItem 创建时都会创建对应的边
- server 启动时创建基础的 metadata 边（ACTOR, IN_SCENE）
- MemoryItem 创建时创建完整的边（OWNS_MEMORY, IN_SCENE, HAS_CHARACTER, FROM_CONV, CONV_IN_SCENE, CONV_HAS_CHARACTER）
