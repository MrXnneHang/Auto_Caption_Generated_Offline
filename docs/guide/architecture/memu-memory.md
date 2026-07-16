# memU 记忆（CLI，实验性）

本页描述 **memU** 作为**与 wikimem 并列的、可选的第二记忆后端**如何集成。定位与决策见
[ADR-0003](/adr/0003-memu-cli-integration)（及其前身 [ADR-0002](/adr/0002-memu-design-not-dependency)）。

::: warning 实验性 · 默认关闭
memU 后端默认不启用，需要 **Rust 工具链**、可由 uv 解析的 **Python 3.13**，以及一个
**OpenAI 兼容 embedding 端点**（硬前置）。默认记忆后端仍是
[wikimem](https://wikimem.xnnehang.top/zh/)。
:::

## 上游形态（2026-07 pivot 之后）

- 上游只发布/更新 **`memu-cli`**（`memu-py` 冻结待归档），CLI 是唯一受支持的集成面，
  按**短生命周期进程**设计。
- **memU 不做 LLM 抽取**：`memu commit` 持久化宿主准备好的 recall files（record seam）；
  memory track 的文件**按行切 segment**（`#` 标题与空行跳过）——每行就是一条可检索记忆。
- `memu retrieve` 是 0 LLM 的 embedding 检索，stdout 输出 JSON（inject seam）。
- `memu-cli` 要求 Python 3.13 + maturin/Rust 编译核，本项目钉在 3.11，无法同进程导入。

## 架构

```
Python 3.11 主进程 (lab)                     短生命周期 Python 3.13 子进程（uv 拉起，环境有缓存）
┌───────────────────────────────────┐
│ src/lab/plugins/memu (HookPlugin)  │ spawn  ┌─────────────────────────────────────┐
│ on_before_turn ───────────────────────────> │ uv run --isolated --no-project       │
│   memu retrieve "<query>" → 注入   │        │   --python 3.13 --with packages/memU │
│ on_after_turn（后台任务）:          │        │   memu retrieve / memu commit -      │
│   抽取 LLM（继承 chat）             │        │ env: MEMU_DB / MEMU_EMBED_* /        │
│   → 影子 markdown 追加行            │        │      MEMU_CONFIG_ENV（私有）          │
│   → memu commit -（stdin JSON）    │        └─────────────────────────────────────┘
│ fail-open + 超时；无常驻进程        │        store: <memory_dir>/memu.sqlite3
└───────────────────────────────────┘
        影子记忆文件（事实源）: <memory_dir>/recall/<category>.md
```

- **读**（`on_before_turn`）：`memu retrieve` 拿 segments，按 `budget_tokens` 注入
  `- 行内容`；超时/失败即本轮不注入（fail-open）。
- **写**（`on_after_turn`，后台）：插件自己做单次 LLM 抽取（与 wikimem 同一套
  category/name/content 契约、同样默认继承 `lab.toml` chat 配置），条目以 `name：content`
  行追加到影子 markdown，然后把**整个文件** `memu commit`——memU 按行 diff 重建 segments，
  未变的行保留 embedding。
- **影子文件是事实源**：人可读可改、可 diff 可回滚；memU 的 SQLite 只是索引投影，随时可由
  影子文件重建（逐个重新 commit 即可）。
- **store 隔离**：`MEMU_DB`、`MEMU_CONFIG_ENV` 都指到 `memory_dir` 下，绝不与用户全局
  `~/.memu/config.env` 串味。
- 首次调用触发 maturin 源码构建（数分钟，uv 缓存后续复用）；构建期间召回 fail-open。

## 与 wikimem 的取舍

| | wikimem（默认） | memU（实验，CLI） |
|---|---|---|
| 进程 | 同进程（uv workspace 成员） | 每次调用一个 Python 3.13 短生命周期子进程 |
| 存储 | 扁平 markdown 分类文件 | 影子 markdown（事实源）+ SQLite（索引） |
| 抽取 | 插件内单次 LLM | 插件内单次 LLM（同一契约；memU 自身 0 LLM） |
| 召回 | BM25 + 可选 embedding 融合，毫秒级 | embedding 检索，秒级（子进程 + embedding HTTP） |
| 关联 | 内容内 `[[wiki-link]]` | 无 |
| 前置 | 无额外前置 | Rust + Python 3.13 + embedding 端点（必须） |

两者可单独或同时启用；同时启用时两套记忆各自注入，适合做**对照评测**。

## 启用（opt-in）

在某个 profile 里把 `memu` 加进 `[plugins] enabled`，并配 `[plugins.memu]`：

```toml
[plugins]
enabled = [
    # ... 既有插件 ...
    "memu",
]

[plugins.memu]
memory_dir = "memu_memory"        # memU 状态目录（相对 workspace_root）
search_limit = 5
budget_tokens = 800
# 抽取 LLM：留空 = 继承 lab.toml 的 chat 模型配置
extraction_base_url = ""
extraction_model = ""
extraction_api_key = ""
# embedding（OpenAI 兼容）：必填，留空则插件禁用
embedding_base_url = "https://your-embed-endpoint/v1"
embedding_model = "text-embedding-3-small"
embedding_api_key = "sk-..."
# 子进程
python_version = "3.13"
retrieve_timeout = 15.0           # 召回超时（超时本轮不注入）
commit_timeout = 600.0            # 写入超时（首次含源码构建，需宽松）
```

全部配置项见 `src/lab/plugins/memu/plugin.toml` 的 `config_schema`。

## 本地 smoke（无需任何外部 key）

用一个本地假 embedding 端点即可端到端验证 commit → retrieve（也是排障手段）。

1. 起一个确定性的假 `/v1/embeddings`（stdlib 即可，向量由文本哈希导出）。
2. 环境变量指向它并选好 store：

```bash
export MEMU_BASE_URL=http://127.0.0.1:8901/v1
export MEMU_API_KEY=fake
export MEMU_EMBED_PROVIDER=openai
export MEMU_DB=./.memu-smoke/memu.sqlite3

echo '{"recall_files": [{"name": "preferences", "track": "memory",
  "description": "test", "content": "# preferences\n手冲咖啡：只喝手冲，不加糖\n"}]}' \
  | uv run --isolated --no-project --python 3.13 --with ./packages/memU memu commit -

uv run --isolated --no-project --python 3.13 --with ./packages/memU memu retrieve "咖啡偏好"
```

retrieve 的 JSON 里应能看到 `segments[].text = "手冲咖啡：只喝手冲，不加糖"` 带相似度分数。
首次运行会先做 maturin 构建（需要 Rust）。热路径实测约 **2.0 s/次**（Windows，本地假
embedding，空库 retrieve；真实端点再加一次 embedding HTTP 往返）。

::: danger 当前 pin（aae3d44）的上游回归
上游 main 处于 pivot 中途：embedding client 返回 `(vectors, response)` 元组，而 agentic 面按
裸列表消费——**该 pin 上 `commit` 与带数据的 `retrieve` 会报错**（空库 retrieve 正常）。插件
fail-open，表现为不注入/不记忆。已上报上游
[NevaMind-AI/memU#499](https://github.com/NevaMind-AI/memU/issues/499)；等上游修复、镜像同步后
re-pin 即可，详见 [ADR-0003](/adr/0003-memu-cli-integration) 的「当前已知阻塞」。
:::

## 已知代价

- 每次召回付一次子进程成本（秒级，慢于 wikimem 的毫秒级）；不可接受时的逃生门（常驻
  worker）在 [ADR-0003](/adr/0003-memu-cli-integration) 的「后果」里有记录，暂不实现。
- 首次启动有 Rust 构建延迟；构建期间召回不注入（fail-open）。
- 承接 memu-cli 的 Beta 抖动风险（pivot 本身即例证）；缓解 = 子模块 pin + 最小 CLI 契约面。
