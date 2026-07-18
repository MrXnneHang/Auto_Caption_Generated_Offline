# memU 记忆（CLI，实验性）

本页描述 **memU** 作为**与 wikimem 并列的、可选的第二记忆后端**如何集成。定位与决策见
[ADR-0003](/adr/0003-memu-cli-integration)（及其前身 [ADR-0002](/adr/0002-memu-design-not-dependency)）。

::: warning 实验性 · 默认关闭
memU 后端默认不启用，需要 **Rust 工具链**、可由 uv 解析的 **Python 3.13**，以及一个
**OpenAI 兼容 embedding 端点**（硬前置）。默认记忆后端仍是
[wikimem](https://wikimem.xnnehang.top/zh/)。
:::

## 上游形态：两个集成面（memU ADR-0008）

上游有**两个分层的集成面**，共享同一 store，可自由混用：

- **Surface A —— zero-code hooks（`memu-cli`）**：面向 drop-in 用户；hook 契约 = `on_turn`
  （回合后异步记录）+ `on_prompt`（生成前同步注入）。本项目当前接的就是这一面的语义。
- **Surface B —— programmatic API（`memu-py`）**：面向把 memU 内嵌进自己 agent 的 builder，
  代码里直接调 retrieve / memorize。`memu-py` 正在经历 trajectory-as-source **大重构，尚未
  就绪**——就绪后本项目会**再接一条 PY 连接**（双面并存，不二选一），同样从子模块源码构建。
- 当前 CLI 面：**memU 不做 LLM 抽取**——`memu commit` 持久化宿主准备好的 recall files
  （memory track 按行切 segment，`#` 标题与空行跳过）；`memu retrieve` 是 0 LLM 的 embedding
  检索，stdout 输出 JSON。要求 Python 3.13 + maturin/Rust，本项目（3.11）无法同进程导入。

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

retrieve 的 JSON 里应能看到 `segments[].text = "手冲咖啡：只喝手冲，不加糖"` 带相似度分数
（本 round-trip 已在 pin `f51673e` 上验证通过）。首次运行会先做 maturin 构建（需要 Rust）。
热路径实测 **2.1–2.4 s/次**（Windows，本地假 embedding；真实端点再加一次 embedding HTTP 往返）。

::: tip 曾有的上游回归（已解决）
2026-07-16 集成时发现上游 embed 契约回归（[memU#499](https://github.com/NevaMind-AI/memU/issues/499)），
上游当日以 [#504](https://github.com/NevaMind-AI/MemU/pull/504) 修复；re-pin 至 `f51673e` 后
round-trip 已验证。这也是本集成「contributor dogfooding 回路」的首个产出。
:::

## re-pin 流程（升级子模块时）

1. `git -C packages/memU fetch origin && git -C packages/memU checkout <新 commit>`，父仓 `git add packages/memU`
2. **必须让 uv 重建**：uv 对路径源的缓存只看 `pyproject.toml` 的 mtime——版本号没变时 re-pin 会
   **静默复用旧构建**（`--refresh-package` / `uv cache clean` 都不解）。插件已内置 fresh-build
   guard 自动处理；**手动跑 CLI 时**需 `touch packages/memU/pyproject.toml`
3. 跑上面的 keyless smoke 验证 commit → retrieve round-trip

## 已知代价

- 每次召回付一次子进程成本（实测 2.1–2.4 s，慢于 wikimem 的毫秒级）；根治路径是未来的
  **memu-py（Surface B）连接**（见 [ADR-0003](/adr/0003-memu-cli-integration)），届时双面并存。
- 首次启动有 Rust 构建延迟；构建期间召回不注入（fail-open）。
- **uv 路径源静默缓存坑**：re-pin 后版本号没变时 uv 会复用旧构建（见上方 re-pin 流程）；
  插件已内置 guard，手动 CLI 需自己 touch。
- 承接 memU 的 Beta 抖动：下一个**已宣告的破坏性变更**是 CLI 命令收敛（`memorize`/`retrieve`
  成为唯一命令对，`commit`/`list-files` 退场，无弃用期），届时 re-pin 需同步适配插件。
