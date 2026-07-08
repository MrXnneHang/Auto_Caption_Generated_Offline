# Gotcha

Non-obvious conventions and pitfalls. Read this before your first PR.

## Git Workflow

- **Main branch**: `dev`. Always branch from it. Submodule main branches differ:
  - `frontend/` → `xnne-dev`
  - `launcher/` → `main`
- **No force push** unless real conflict + explicit user consent.
- **Branch from fresh dev**: sync local `dev` to remote before creating a new branch. Never branch from an already-merged PR branch — it carries stale commits and makes review painful.
- **Submodule sync**: after merging a submodule PR, update the parent repo's submodule pointer in a separate commit.

## Config Files

- `config/lab.toml` and `profiles/baoqiao.toml` contain **user-local settings** (API keys, private preferences).
- Committing new fields or schema changes is fine; committing keys or personal overrides is not.
- Use `git stash push -m "local config" -- config/lab.toml profiles/baoqiao.toml` before switching branches or merging.
- Never `git reset --hard` these files — use stash to preserve local changes.

## PR Template

PRs must follow `.github/PULL_REQUEST_TEMPLATE.md`. Three sections:

```markdown
## 动机
Why this change exists. Link related issues (fixes #123 / closes #123 / related to #123).

## 解决方案
What you did (if the PR is large).

## 类型
Check the matching type checkbox(es).
```

Available types: feat / fix / docs / refactor / perf / dx / workflow / types / wip / test / build / ci / chore / deps / release.

## Lazy Imports

Heavy libraries (`torch`, `pandas`, `modelscope`, etc.) **must** use lazy import to keep server startup fast. Pattern:

```python
# At module level — no import
# Inside the function that needs it:
def some_function():
    import torch  # Lazy-import
    ...
```

Files using this pattern are marked with `# Lazy-import` comments.

## Model Installation

Use the **Launcher's Models page** for downloading models — not `justfile` recipes. The Launcher calls `scripts/lab_download.py` which covers: Sherpa, Silero VAD, GSV-Lite, Genie-TTS, Qwen TTS, BGE-M3 embedding, LLM translate.

Exception: **Qwen ASR** models are not in the Launcher yet — use `just install-qwen-asr`.

## Plugin Config Sync

After modifying a plugin's Pydantic config model, run `just sync-plugin` to regenerate the `plugin.toml` `[config]`/`[config_schema]` sections. Forgetting this causes config mismatch between code and TOML.
