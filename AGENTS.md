# AGENTS.md

XnneHangLab (魔女の実験室) is an AI desktop companion featuring LLM-driven Live2D chat, TTS/ASR, and long-term memory. Python 3.11 backend (FastAPI + WebSocket), Electron + React frontend, download engine and model management via Launcher.

## Project Structure

```
XnneHangLab/
├── src/lab/                      # Python backend (core)
│   ├── agent/                    #   Agent engine — factory, core, LLM adapters
│   ├── plugins/                  #   Plugin implementations (mood_chat, memory, visual_observer, ...)
│   ├── plugin/                   #   Plugin framework (config, loader, hooks)
│   ├── conversations/            #   Conversation flow, TTS manager, chat history
│   ├── asr/                      #   ASR providers (Sherpa-ONNX, Qwen ASR)
│   ├── api/                      #   FastAPI routes (chat, ASR, TTS, embedding, translate, ...)
│   ├── mcp/                      #   MCP servers (timeemi, vision, tool)
│   ├── tools/                    #   Built-in tool implementations
│   ├── config_manager/           #   Settings loader, package manager, profile validator
│   ├── profile/                  #   Character profile handling
│   ├── translate/                #   Translation engine integrations (DeepLX, LLM)
│   ├── service_context.py        #   Per-session runtime container (agent, LLM, Live2D, translate)
│   └── websocket_handler.py      #   WebSocket message routing & conversation lifecycle
├── memory_bench/                 # Memory system benchmark & graph pipeline
│   ├── scripts/                  #   Pipeline scripts (annotate, replay_mem0, claimify, graph, ...)
│   ├── server/                   #   Standalone chat server with memory retrieval
│   ├── data/                     #   Events/claims JSONL storage
│   ├── state/                    #   Checkpoints, qdrant storage, state.sqlite
│   ├── logs/                     #   Execution traces and exports
│   └── tests/                    #   Memory bench tests (pytest)
├── frontend/                     # [submodule] Electron + React UI → see frontend/CLAUDE.md
├── launcher/                     # [submodule] Vite-based launcher
├── packages/                     # [submodule] Local workspace members
│   ├── Qwen3-ASR/                #   Qwen ASR (OpenVINO)
│   ├── GSV-TTS-Lite/             #   GPT-SoVITS TTS
│   ├── Genie-TTS/                #   Genie TTS
│   └── Qwen3-TTS/                #   Qwen TTS (via pyproject workspace)
├── config/                       # Runtime config
│   └── lab.toml                  #   Main config (ASR, agent, TTS, plugins)
├── profiles/                     # Character profiles (TOML)
├── models/                       # Pre-trained model storage (ASR, TTS, embedding)
├── tests/                        # Backend tests (pytest)
├── scripts/                      # Utility scripts (batch TTS, model download, ...)
├── docs/                         # VitePress documentation site
└── justfile                      # Dev commands (100+ recipes)
```

## Architecture

```
Frontend (Electron/React)  ←WebSocket→  Backend (FastAPI)  ←subprocess/API→  Services
         Live2D + UI                    Agent + Plugins                ASR / TTS / LLM / MCP
```

- Frontend connects via WebSocket; backend pushes events (`audio`, `control`, `model`, `history`)
- Agent uses OpenAI-compatible LLM API (single adapter, works with any compatible provider)
- Plugins hook into agent lifecycle via `HookManager` (pre/post processing, tool injection)
- ASR/TTS run as in-process FastAPI sub-apps or external subprocesses
- MCP servers provide tool/vision/time capabilities to the agent

### Backend request flow

```
WebSocket message
  → websocket_handler.py (route by MessageType: CONVERSATION / GROUP / HISTORY / INTERRUPTS)
  → conversation_handler.py (trigger, interrupt, task lifecycle)
  → agent_core.py (plugin hooks → LLM call → tool execution → response)
  → tts_manager.py (text → audio chunks, streamed back via WebSocket)
```

### Adding a new plugin

1. Create `src/lab/plugins/your_plugin/` with `__init__.py`
2. Implement plugin class extending the plugin interface
3. Define Pydantic config model for `plugin.toml` schema
4. Run `just sync-plugin` to generate config metadata
5. Register in profile TOML under `[plugins]`

## Memory Bench Pipeline

Offline pipeline: raw conversations → structured memory → Neo4j knowledge graph.

```
build-index → annotate (LLM #1) → compile-events
  → mem0 ingest → mem0 export
  → claimify (LLM #3) → compile-claims
  → graph nodes/edges → Cypher → Neo4j
```

Quick-start entries at different pipeline stages:
- `just mem0-run-from-annotate` — full pipeline from scratch
- `just mem0-run-from-ingest` — skip annotation, reuse events
- `just mem0-run-from-claim` — skip annotation + ingest, rerun claims
- `just mem0-run-real-time` — start realtime chat server with memory

## Dev Commands

```bash
just dev                # Clean build + start server (uv lock → run_server.py)
just server             # Start server directly
just mcp-server         # Start MCP servers (timeemi + vision + tool)

just test               # Run all tests (backend + memory_bench)
just fmt                # Ruff format + import sort
just lint               # Pyright + Ruff check

just sync-dev           # Checkout dev, pull, sync submodules
just sync-plugin        # Sync plugin config metadata
just reload-lab-setting # Regenerate config/lab.toml with new defaults

just docs-dev           # Start VitePress dev server
```

## Commit Convention (Gitmoji)

Format: `:gitmoji: type: description`

| gitmoji | type | usage |
|---------|------|-------|
| `:sparkles:` | feat | New feature |
| `:bug:` | fix | Bug fix |
| `:recycle:` | refactor | Refactor |
| `:art:` | fix/style | Code format/structure improvement |
| `:zap:` | perf | Performance |
| `:arrow_up:` | deps/chore | Dependency bump |
| `:memo:` | docs | Documentation |
| `:white_check_mark:` | test | Tests |
| `:wrench:` | chore | Config files |
| `:fire:` | chore | Remove code/files |

Example: `:sparkles: feat: OCR 累积去重 — 归一化后精确匹配防止抖动文本重复计数`

## Key Conventions

- **Python 3.11**, `uv` for package management, `pyright` strict, `ruff` lint
- **Lazy imports**: heavy libraries (`torch`, `pandas`, etc.) must use lazy import (marked `# Lazy-import`) to keep startup fast
- **Config**: TOML-based — `config/lab.toml` (global), `profiles/*.toml` (per-character)
- **Language**: UI text in Chinese, code/comments in English
- **Branching**: `dev` is the main branch; create feature/fix branches from it
- **Protected files**: never commit `config/lab.toml` or `profiles/baoqiao.toml` — these contain local overrides. Use `stash` to preserve them during branch operations
- **No force push** unless real conflict + explicit user consent

## Communication Style

Experienced peer, not a teacher. Organize by conclusion, not explanation.

Error format: cause (one line) → fix (command) → verify (how to confirm).

Hard rules:
- Don't repeat a solution the user already said failed
- Don't wrap simple answers in long explanations
- Don't hedge with "it depends" on binary questions — give a recommendation
- Don't add motivational endings or meta-commentary
- Say it, then stop
