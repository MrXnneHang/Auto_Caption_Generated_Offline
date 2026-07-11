# 贡献指南

感谢你愿意参与 XnneHangLab 的开发。

---

## 先看哪些文档

开始之前，建议先熟悉这些架构页：

- [架构概览](./architecture/)
- [Agent 模块](./architecture/agent)
- [API 模块](./architecture/api)
- [ASR 模块](./architecture/asr)
- [工具系统](./architecture/tools)
- [Conversations 模块](./architecture/conversations)
- [Config 模块](./architecture/config)
- [Skill 系统](./architecture/skills)
- [Memory Agent](./architecture/memory-agent)

> [!TIP]
> 推荐先读 [架构概览](./architecture/)，再按需深入具体模块。

---

## 参与方式

- 报告问题或提建议：直接去 [Issues](https://github.com/XnneHangLab/XnneHangLab/issues)
- 修复 Bug、添加功能、改进文档：创建分支后提 PR

---

## 工具准备

| 工具 | 用途 | 安装 |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python 项目管理 | [安装指南](https://docs.astral.sh/uv/getting-started/installation/) |
| [just](https://github.com/casey/just) | 命令执行工具 | [安装指南](https://github.com/casey/just#installation) |

Windows 如果不能直接运行 `just`，可以打开 `justfile` 手动执行对应命令。

---

## 开发流程

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/<your-name>/XnneHangLab.git
cd XnneHangLab

# 2. 安装依赖
uv lock
uv sync

# 3. 基于最新 dev 创建分支
git checkout dev
git pull origin dev
git checkout -b feat/your-feature

# 4. 开发并自检
just fmt
just lint
just test

# 文档类 PR 可以本地预览
just docs-clean
just docs-dev

# 5. 推送并发起 PR
git push origin feat/your-feature
```

---

## PR 规则

- 标题建议带 gitmoji，例如 `:sparkles: 新增 xxx`
- 目标分支统一为 `dev`
- 描述请遵循 [`.github/PULL_REQUEST_TEMPLATE.md`](https://github.com/XnneHangLab/XnneHangLab/blob/dev/.github/PULL_REQUEST_TEMPLATE.md)
- 如果本次改动覆盖了 [RoadMap](./roadmap) 中的某项，请在同一个 PR 里同步更新它

---

## 文档同步规则

`CONTRIBUTING.md` 与 `docs/guide/contributing.md` 应保持同步：

- 修改其中任意一个时，应同步更新另一个
- 区别仅在于链接形式：文档站使用相对路径，仓库根文档通常使用完整 URL

---

## CI 检查项

每个 PR 会自动触发这些检查：

- `ruff check`
- `ruff format --check`
- `ty check --error-on-warning`
- `pytest`

---

## 给 AI 协作者的约束

如果你在用 Cursor、Copilot、Claude 或其他 AI 编码工具，请额外注意：

1. 不要直接往 `dev` 或 `gh-pages` 推送提交，统一走 PR
2. 不要删除 `dev` 或 `gh-pages` 分支
3. 每个 PR 开始前都先同步最新 `dev`
4. PR 合并或关闭后，及时删除远程功能分支
5. 修改 `CONTRIBUTING.md` 时，同步修改这份文档
