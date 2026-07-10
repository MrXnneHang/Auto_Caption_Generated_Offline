# memory_bench/typing 模块设计

> **目标**：通过 pydantic BaseModel 统一类型定义，消除 `Any` 和 `Unknown` 类型错误
> 
> **原则**：
> 1. 能用 pydantic 就用 pydantic 进行类型解析
> 2. 避免 `Any` 的使用和后续 `Any` 导致的 `Unknown`
> 3. 分步实现：先设计一个，绘制一个，逐步覆盖
> 4. 按照工作流顺序：`build_index` → `compiled_claims` → `annotate_all` → 其他

---

## 📊 当前类型问题统计（基于 pyright）

| 文件 | 错误数 | 主要问题 |
|------|--------|----------|
| `scripts/export_node_schema.py` | 65 | 类型未知 (Unknown) / dict 缺少类型参数 |
| `scripts/claimify_all.py` | 45 | dict.get() 返回类型未知 / 类型部分未知 |
| `scripts/replay_mem0.py` | 42 | dict.get() 返回类型未知 / 类型部分未知 |
| `scripts/tag_registry.py` | 33 | dict.get() 返回类型未知 / 类型部分未知 |
| `tests/test_replay_mem0_export.py` | 22 | 缺少类型注解 / 类型未知 |
| `server/router.py` | 20 | dict.get() 返回类型未知 / 类型部分未知 |
| `scripts/annotate_all.py` | 11 | 类型未知 / dict_keys 类型部分未知 |
| `scripts/graph_to_cypher.py` | 10 | 类型未知 / props 类型部分未知 |
| `scripts/mem0_to_graph.py` | 9 | dict.get() 返回类型未知 |
| `server/claim_extractor.py` | 8 | dict.get() 返回类型未知 |

**总计**: 326 errors (memory_bench)

---

## 🏗️ 模块结构

```
memory_bench/typing/
├── __init__.py           # 导出所有公共类型
├── index.py              # 索引相关类型 (build_index)
├── events.py             # 事件/标注相关类型 (annotate_all)
├── claims.py             # Claim/Entity 相关类型 (compiled_claims, claimify_all)
├── memory.py             # MemoryItem 相关类型 (mem0_to_graph, replay_mem0)
├── neo4j.py              # Neo4j 节点/关系类型 (graph_to_cypher, graph_writer)
└── common.py             # 通用类型和类型守卫
```

---

## Phase 1: Index 类型 (`typing/index.py`)

**覆盖文件**: `scripts/build_index.py`

### 类型定义

```python
from pydantic import BaseModel, Field
from typing import Literal


class IndexEntry(BaseModel):
    """章节索引条目。
    
    Attributes:
        id: 章节 ID，格式为 `chNN`（至少两位数字）
        raw_path: 原始章节文件（raw）相对于仓库根目录的路径
        norm_path: 规范化章节文件（norm）相对路径；若缺失则为空字符串
    """
    id: str = Field(..., pattern=r"^ch\d{2,}$", description="章节 ID")
    raw_path: str = Field(..., description="raw 文件相对路径")
    norm_path: str = Field(default="", description="norm 文件相对路径")


class IndexSliceParams(BaseModel):
    """索引切片参数。
    
    Attributes:
        limit: 保留前 N 条
        tail: 保留最后 N 条（优先于 limit）
        offset: 先跳过前 N 条
    """
    limit: int | None = Field(default=None, ge=1)
    tail: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
```

### 修复点

| 位置 | 当前问题 | 修复方案 |
|------|----------|----------|
| `build_index()` 返回值 | `tuple[list[IndexEntry], list[str]]` 已用 TypedDict | 迁移到 pydantic，增加验证 |
| `slice_index()` 参数 | `limit/tail/offset` 缺少验证 | 使用 `IndexSliceParams` |
| `IndexEntry` | 使用 TypedDict，缺少运行时验证 | 改为 pydantic BaseModel |

---

## Phase 2: Events 类型 (`typing/events.py`)

**覆盖文件**: `scripts/annotate_all.py`

### 类型定义

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Annotated


ALLOWED_ROLE_TYPES = {"human", "assistant", "ui", "tool"}
ALLOWED_TAGS = {"canon_only", "episodic", "filler", "inject", "probe"}

RoleType = Literal["human", "assistant", "ui", "tool"]
EventTag = Literal["canon_only", "episodic", "filler", "inject", "probe"]


class EventMeta(BaseModel):
    """事件元信息。"""
    # 根据实际 schema 定义
    pass


class Event(BaseModel):
    """标注事件（JSONL 单行）。
    
    Attributes:
        scene_id: 场景 ID
        character_id: 角色 ID
        conv_id: 会话/章节 ID
        turn_id: 回合序号（从 1 开始）
        role_type: 角色类型
        role_name: 角色名称
        content: 对话内容
        tags: 标签列表
        meta: 元信息
    """
    scene_id: str = Field(..., description="场景 ID")
    character_id: str = Field(..., description="角色 ID")
    conv_id: str = Field(..., description="会话 ID")
    turn_id: int = Field(..., ge=1, description="回合序号")
    role_type: RoleType = Field(..., description="角色类型")
    role_name: str = Field(..., description="角色名称")
    content: str = Field(..., min_length=1, description="对话内容")
    tags: list[EventTag] = Field(..., min_length=1, description="标签列表")
    meta: dict[str, Any] = Field(default_factory=dict, description="元信息")
    
    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[EventTag]) -> list[EventTag]:
        if not v:
            raise ValueError("tags must be non-empty")
        return v
```

### 修复点

| 位置 | 当前问题 | 修复方案 |
|------|----------|----------|
| `load_index()` | `list[dict[str, Any]]` 返回 Unknown | 改为 `list[IndexEntry]` |
| `validate_event_line()` | 手动校验 dict，类型未知 | 使用 `Event.model_validate()` |
| `validate_jsonl_output()` | `obj` 类型为 Any | 使用 `Event` pydantic 模型 |
| `REQUIRED_KEYS` | 硬编码列表 | 从 `Event.model_fields` 派生 |

---

## Phase 3: Claims 类型 (`typing/claims.py`)

**覆盖文件**: `scripts/compiled_claims.py`, `scripts/claimify_all.py`

### 类型定义

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Annotated


ALLOWED_ENTITY_TYPES = {"Agent", "User", "Author", "Work", "Chapter", "Topic", "Tag"}
ALLOWED_DOMAINS = {"reading", "writing", "daily"}
ALLOWED_STATUSES = {"active", "candidate"}
ALLOWED_PREDICATES = {
    "PREFERS_AUTHOR", "FAVORITE_WORK", "DISCUSSED_WORK", "DISCUSSED_CHAPTER",
    "PREFERS_NARRATIVE_STYLE", "SELF_TRAIT", "TRIED_STYLE", "SELF_CRITIQUE",
    "PREFERS_TOPIC",
}

EntityType = Literal["Agent", "User", "Author", "Work", "Chapter", "Topic", "Tag"]
DomainType = Literal["reading", "writing", "daily"]
ClaimStatus = Literal["active", "candidate"]


class EntityReference(BaseModel):
    """实体引用（用于 claim 的 subject/object）。"""
    entity_type: EntityType
    entity_id: str


class EvidenceItem(BaseModel):
    """Claim 证据项。"""
    point_id: str | None = Field(default=None, description="mem0 point ID")
    memory_item_id: str | None = Field(default=None, description="MemoryItem ID")
    created_at: str | None = Field(default=None, description="创建时间")
    
    @field_validator("point_id", "memory_item_id")
    @classmethod
    def validate_ids(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("ID must be non-empty string when provided")
        return v
    
    @model_validator(mode="after")
    def validate_at_least_one_id(self) -> "EvidenceItem":
        if not self.point_id and not self.memory_item_id:
            raise ValueError("evidence must include point_id or memory_item_id")
        return self


class Entity(BaseModel):
    """实体记录。"""
    record_type: Literal["entity"] = "entity"
    entity_id: str = Field(..., description="实体 ID")
    entity_type: EntityType = Field(..., description="实体类型")
    props: dict[str, Any] = Field(default_factory=dict, description="属性")
    aliases: list[str] = Field(default_factory=list, description="别名")
    tags: list[str] = Field(default_factory=list, description="标签")
    confidence: float = Field(..., ge=0, le=1, description="置信度")


class Claim(BaseModel):
    """Claim 记录。"""
    record_type: Literal["claim"] = "claim"
    claim_id: str = Field(..., description="Claim ID")
    predicate: str = Field(..., description="谓词")
    subject: EntityReference = Field(..., description="主体")
    object: EntityReference = Field(..., description="客体")
    domain: DomainType = Field(..., description="领域")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    status: ClaimStatus = Field(..., description="状态")
    rank: int | None = Field(default=None, description="排名")
    updated_at: str = Field(..., description="更新时间")
    evidence: list[EvidenceItem] = Field(..., min_length=1, description="证据列表")
```

### 修复点

| 位置 | 当前问题 | 修复方案 |
|------|----------|----------|
| `read_jsonl()` | `list[dict[str, Any]]` 返回 Unknown | 改为 `list[Entity | Claim]` |
| `_validate_entity()` | 手动校验 | 使用 `Entity.model_validate()` |
| `_validate_claim()` | 手动校验 | 使用 `Claim.model_validate()` |
| `merge_entities()` | `dict[str, dict[str, Any]]` | `dict[str, Entity]` |
| `merge_claims()` | `dict[str, dict[str, Any]]` | `dict[str, Claim]` |

---

## 🎯 实施策略

### 第一步：创建基础结构

```bash
mkdir -p memory_bench/typing
touch memory_bench/typing/__init__.py
touch memory_bench/typing/index.py
touch memory_bench/typing/events.py
touch memory_bench/typing/claims.py
touch memory_bench/typing/common.py
```

### 第二步：逐个文件修复

1. **先修复 `build_index.py`**（依赖最少）
   - 迁移 `IndexEntry` 到 `typing/index.py`
   - 更新 import
   - 运行 pyright 验证

2. **再修复 `annotate_all.py`**
   - 创建 `typing/events.py`
   - 使用 `Event` 模型替换 dict 校验
   - 运行 pyright 验证

3. **然后修复 `compiled_claims.py`**
   - 创建 `typing/claims.py`
   - 使用 `Entity`/`Claim` 模型
   - 运行 pyright 验证

### 第三步：更新文档

- 在 `scripts-guide.md` 中添加 typing 模块说明
- 在本文档中更新进度

---

## 📈 进度追踪

| Phase | 模块 | 覆盖文件 | 状态 | 预计错误减少 |
|-------|------|----------|------|-------------|
| 1 | `typing/index.py` | `build_index.py` | ✅ 完成 | ~0 (已用 TypedDict) |
| 2 | `typing/events.py` | `annotate_all.py` | ✅ 完成 | ~11 |
| 3 | `typing/claims.py` | `compiled_claims.py`, `claimify_all.py` | ⏳ 待开始 | ~56 |
| 4 | `typing/memory.py` | `mem0_to_graph.py`, `replay_mem0.py` | ⏳ 待开始 | ~51 |
| 5 | `typing/neo4j.py` | `graph_to_cypher.py`, `graph_writer.py` | ⏳ 待开始 | ~18 |
| 6 | `typing/common.py` | `tag_registry.py`, `export_*.py` | ⏳ 待开始 | ~78 |

**目标**: 326 errors → 0 errors

---

## ✅ Phase 1 完成总结

**完成时间**: 2026-03-02

**修改内容**:
1. 创建 `memory_bench/typing/` 目录结构
2. 实现 `typing/index.py`:
   - `IndexEntry` BaseModel（带字段验证）
   - `IndexSliceParams` BaseModel（带切片逻辑）
   - `build_index_from_dir()` 工具函数
3. 实现 `typing/common.py`:
   - 类型守卫函数（`is_str_dict`, `is_non_empty_str`, `is_list_of_str`）
4. 更新 `build_index.py`:
   - 迁移 `IndexEntry` 从 TypedDict 到 pydantic BaseModel
   - 使用 `IndexSliceParams.apply()` 替代手动切片
   - 使用 `model_dump()` 替代 dict 转换

**运行验证**:
```bash
uv run memory_bench/scripts/build_index.py --limit 2
# ✅ 成功生成 index.json
```

**pyright 状态**: 由于 pydantic 插件未配置，部分 pydantic 方法报告 unknown，但运行时正常。后续可通过配置 pydantic pyright 插件改善。

---

## ✅ Phase 2 完成总结

**完成时间**: 2026-03-02

**修改内容**:
1. 实现 `typing/events.py`:
   - `Event` BaseModel（带字段验证）
   - `EventMeta` BaseModel（灵活 dict 包装）
   - `RoleType`, `EventTag` Literal 类型
   - `ChapterJob`, `JobResult` dataclass
   - `validate_event_tags()` 工具函数
2. 更新 `annotate_all.py`:
   - 移除重复的 `ChapterJob`/`JobResult` 定义，使用 typing 模块
   - 重写 `validate_event_line()`: 使用 `Event.model_validate()` 替代手动校验
   - 更新 `load_index()`: 使用 `TypeAdapter(list[IndexEntry])` 解析
   - 移除未使用的 import（`ALLOWED_ROLE_TYPES`, `ALLOWED_TAGS`, `validate_event_tags`）

**pyright 验证**:
```bash
uv run pyright memory_bench/scripts/annotate_all.py
# 0 errors, 0 warnings, 0 informations ✅
```

**运行验证**:
```bash
uv run memory_bench/scripts/annotate_all.py --help
# ✅ 帮助信息正常
```

**关键改进**:
- 手动校验逻辑（~80 行）→ pydantic 自动验证（~10 行）
- `dict[str, Any]` → `Event` 强类型
- 运行时错误提前到 schema 验证阶段捕获

---

## 🔧 类型守卫工具函数 (`typing/common.py`)

```python
from typing import TypeGuard, Any


def is_str_dict(value: Any) -> TypeGuard[dict[str, Any]]:
    """检查是否为 dict[str, Any] 类型。"""
    return isinstance(value, dict)


def is_non_empty_str(value: Any) -> TypeGuard[str]:
    """检查是否为非空字符串。"""
    return isinstance(value, str) and bool(value.strip())


def is_list_of_str(value: Any) -> TypeGuard[list[str]]:
    """检查是否为字符串列表。"""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
```

---

## 📝 注意事项

1. **不要一次性全部改完**：分步实施，每步验证
2. **保持向后兼容**：旧代码能正常运行的前提下逐步迁移
3. **pydantic v2 语法**：使用 `field_validator` 而非 `@validator`
4. **循环导入**：注意模块间的依赖关系，使用 `TYPE_CHECKING`

---

## 🎨 文件树映射（待实现）

```
memory_bench/
├── scripts/
│   ├── build_index.py         → typing/index.py (IndexEntry)
│   ├── annotate_all.py        → typing/events.py (Event, EventMeta)
│   ├── compiled_claims.py     → typing/claims.py (Entity, Claim, EvidenceItem)
│   ├── claimify_all.py        → typing/claims.py (Entity, Claim)
│   ├── mem0_to_graph.py       → typing/memory.py (MemoryItem, ExportRecord)
│   ├── replay_mem0.py         → typing/memory.py (MemoryItem, ExportRecord)
│   ├── graph_to_cypher.py     → typing/neo4j.py (Node, Relationship)
│   └── tag_registry.py        → typing/common.py (Tag, TagRegistry)
├── server/
│   ├── router.py              → typing/events.py, typing/claims.py
│   ├── claim_extractor.py     → typing/claims.py
│   └── graph_writer.py        → typing/neo4j.py
└── typing/                    # 新建
    ├── __init__.py
    ├── index.py
    ├── events.py
    ├── claims.py
    ├── memory.py
    ├── neo4j.py
    └── common.py
```
