sync-dev:
  git checkout dev
  git pull origin dev
  git submodule update --init --recursive

sync-submodule:
  git submodule sync --recursive
  git submodule update --init --recursive
  git submodule absorbgitdirs


# Config

reload-lab-setting:  # 重新生成 config/lab.toml（升级默认值 / 重置配置）
  uv run get_root
  uv run scripts/reload_lab_setting.py

sync-plugin:  # 同步插件 Pydantic config model 生成的 plugin.toml [config]/[config_schema]
  uv run python scripts/sync_plugin_config_metadata.py

# Docs

docs-dev:
  cd docs && pnpm dev

docs-build:
  cd docs && pnpm build

docs-clean:
  rm -rf docs/.vitepress/cache docs/.vitepress/dist

clean-venv:
  # 如果在 windows 上删不干净，可以运行 `FileLocksmithCLI.exe --kill "D:\tmp\XnneHangLab\.venv"`
  rm ./.venv -rf

dev:
    # 删除所有构建产物和缓存 / 二次操作防止缓存问题恢复代码
    rm -rf packages/*/dist
    rm -rf packages/*/__pycache__
    rm -rf packages/*/*.egg-info
    uv lock --no-cache
    uv run get_root
    uv run run_server.py

# Server Start

mcp-server:
  uv run src/lab/mcp/server/timeemi_server.py & \
  uv run src/lab/mcp/server/vision_server.py & \
  uv run src/lab/mcp/server/tool_server.py & \

server:
  uv run get_root
  uv run run_server.py

# API Router Test

test-proxy:
  curl -X POST "http://localhost:12393/v1/chat/completions" -H "Content-Type: application/json" -d '{"model":"gpt-5.1-2025-11-13","messages":[{"role":"user","content":"hi"}],"stream":false}'

test-proxy-stream:
  curl -X POST "http://localhost:12393/v1/chat/completions" -H "Content-Type: application/json" -d '{"model":"gpt-5.1-2025-11-13","messages":[{"role":"user","content":"hi"}],"stream":true}' --no-buffer

test-proxy-health:
  curl http://localhost:12393/health

test-asr:
  curl -X POST "http://localhost:12393/asr/sherpa/transcribe" -F "file=@./voices/example1.wav"

test-qwen-asr-0-6b:
  curl -X POST "http://localhost:12393/asr/qwen-asr/0.6B/transcribe" -F "file=@./voices/example1.wav"

test-qwen-asr-1-7b:
  curl -X POST "http://localhost:12393/asr/qwen-asr/1.7B/transcribe" -F "file=@./voices/example1.wav"
  
test-vad:
  curl -X POST "http://localhost:12393/asr/sherpa/vad" -F "file=@./voices/example3.opus"

test-sherpa audio='./voices/example3.opus' model_dir='./models/sherpa-onnx-paraformer-zh-2023-09-14' vad_model='./models/silero_vad.onnx' skip_vad='':
  uv run --group sherpa-onnx src/lab/asr/sherpa/probe.py --audio {{ audio }} --model-dir {{ model_dir }} --vad-model {{ vad_model }} {{ if skip_vad != '' { '--skip-vad' } else { '' } }}

test-deeplx:
	curl -X POST "http://127.0.0.1:12393/translate/deeplx" \
	-H "Content-Type: application/json" \
	-d '{ \
		"text": "それでは問題です。澄み渡った青空をゆく、そこに人がいたのなら間違いなく誰もが振り返り、ため息をこぼしてしまうほどの美貌の魔女は、いったい誰でしょう？", \
		"source_language": "auto", \
		"target_language": "ZH" \
	}' \



test-qwen-tts-health server='http://localhost:12393':
  uv run python scripts/test_qwen_tts_client.py --server {{ server }} --mode health

test-qwen-tts-non-stream server='http://localhost:12393' ref_audio='voices/congyin.wav' ref_text='そうそう、この間気分転換に料理したんだ。テスト勉強のモチベを上げるためにも、自分の好物を作ることにしたんだ。あれこれ考え事しちゃって、お鍋吹きこぼれちゃったんだ。けどね、味はすごく美味しくできたよ。君がご近所さんだったら届けてあげたいくらい。この作業通話アプリがもっともっと進化したら。':
  uv run python scripts/test_qwen_tts_client.py --server {{ server }} --mode non-stream --ref-audio {{ ref_audio }} --ref-text {{ ref_text }}

test-qwen-tts-stream server='http://localhost:12393' ref_audio='voices/congyin.wav' ref_text='そうそう、この間気分転換に料理したんだ。テスト勉強のモチベを上げるためにも、自分の好物を作ることにしたんだ。あれこれ考え事しちゃって、お鍋吹きこぼれちゃったんだ。けどね、味はすごく美味しくできたよ。君がご近所さんだったら届けてあげたいくらい。この作業通話アプリがもっともっと進化したら。':
  uv run python scripts/test_qwen_tts_client.py --server {{ server }} --mode stream --ref-audio {{ ref_audio }} --ref-text {{ ref_text }}

test-qwen-tts-stream-play server='http://localhost:12393' ref_audio='voices/congyin.wav' ref_text='そうそう、この間気分転換に料理したんだ。テスト勉強のモチベを上げるためにも、自分の好物を作ることにしたんだ。あれこれ考え事しちゃって、お鍋吹きこぼれちゃったんだ。けどね、味はすごく美味しくできたよ。君がご近所さんだったら届けてあげたいくらい。この作業通話アプリがもっともっと進化したら。':
  uv run python scripts/test_qwen_tts_client.py --server {{ server }} --mode stream-play --stream-chunk-size 8 --playback-buffer-ms 500 --ref-audio {{ ref_audio }} --ref-text {{ ref_text }}

test-gsv-lite-health server='http://localhost:12393':
  curl "{{ server }}/tts/gsv-lite/health"

test-gsv-lite-generate server='http://localhost:12393' output='output/gsv_lite_test.wav' text='你好，这是 gsv-lite 接口测试。' ref_audio_path='models/gsv-tts-lite/luming-v2-pro-plus/emotions/neutral/neutral_01.wav' ref_text='你好，这是参考音频文本。' speaker_audio_path='':
  curl -X POST "{{ server }}/tts/gsv-lite/generate" \
    -H "Content-Type: application/json" \
    -d '{ \
      "text": "{{ text }}", \
      "ref_audio_path": "{{ ref_audio_path }}", \
      "ref_text": "{{ ref_text }}", \
      "speaker_audio_path": "{{ speaker_audio_path }}" \
    }' \
    -o "{{ output }}"

# Model Install (not covered by Launcher)

install-qwen-asr model_dir='./models':
  uv lock
  uv sync
  uv run modelscope download --model xnnehang/Qwen3-ASR-1.7B-INT8_OpenVINO --local_dir {{ model_dir }}/Qwen3-ASR-1.7B-INT8-OpenVINO
  uv run modelscope download --model xnnehang/Qwen3-ASR-0.6B-INT8-OpenVINO --local_dir {{ model_dir }}/Qwen3-ASR-0.6B-INT8-OpenVINO
  uv run modelscope download --model Qwen/Qwen3-ForcedAligner-0.6B --local_dir {{ model_dir }}/Qwen3-ForcedAligner-0.6B


# Code Quality Check

fmt: # 似乎不会检查被 .gitignore 忽略的文件
  uv run ruff check --fix --select I . --exclude packages --exclude .git --exclude justfile --exclude models
  uv run ruff format . --exclude packages --exclude .git --exclude justfile --exclude models

lint:
  uv run pyright src/lab tests memory_bench scripts
  uv run ruff check . --exclude packages --exclude .git --exclude justfile --exclude models

fmt-docs:
  prettier --ignore-path .prettierignore --write '**/*.md'

test:
  uv run pytest tests -vvv
  uv run pytest memory_bench/tests -vvv

test-sentence-divider:
  uv run python scripts/test_sentence_divider.py

prepare-gsv-batch-input input='./data/input.txt' output='data/gsv_batch_input.txt' segment_method='pysbd' max_sentence_len='20':
    uv run python scripts/prepare_gsv_batch_input.py --input {{ input }} --output {{ output }} --segment-method {{ segment_method }} --max-sentence-len {{ max_sentence_len }}

# CI-workflow

ci-install:
  uv lock
  uv sync

ci-test:
  just test

ci-fmt-check:
  just fmt

ci-lint:
  just lint

# memory bench

# just memory-chat-server xnne congyin 聪音 8080
# just memory-chat-server xnne elaina 伊蕾娜 8081
memory-chat-server user_id agent_id agent_name port='8080':
  uv run memory_bench/server/chat_server.py \
    --user-id {{ user_id }} \
    --agent-id {{ agent_id }} \
    --metadata-user-id {{ user_id }} \
    --metadata-user-name {{ user_id }} \
    --metadata-agent-id {{ agent_id }} \
    --metadata-agent-name {{ agent_name }} \
    --metadata-character-id {{ agent_id }} \
    --metadata-character-name {{ agent_name }} \
    --port {{ port }} \
    --enable-graph

memory-chat-cli base_url='http://localhost:8080' endpoint='/v1/chat/completions':
  uv run memory_bench/server/chat_cli.py --base-url {{ base_url }} --endpoint {{ endpoint }}

# 快速调试：使用 /memory/chat 端点（带 session 管理）
memory-chat-cli-memory base_url='http://localhost:8080':
  @echo "Starting chat CLI with /memory/chat endpoint..."
  uv run memory_bench/server/chat_cli.py --base-url {{ base_url }} --endpoint memory

# 快速调试：使用 /v1/chat/completions 端点（OpenAI 兼容）
memory-chat-cli-openai base_url='http://localhost:8080':
  @echo "Starting chat CLI with /v1/chat/completions endpoint..."
  uv run memory_bench/server/chat_cli.py --base-url {{ base_url }} --endpoint openai

build-index limit='' tail='' offset='':
  uv run memory_bench/scripts/build_index.py --force {{ if limit != '' { '--limit ' + limit } else { '' } }} {{ if tail != '' { '--tail ' + tail } else { '' } }} {{ if offset != '' { '--offset ' + offset } else { '' } }}

annotate-all:
  uv run memory_bench/scripts/annotate_all.py

compile-events:
  uv run memory_bench/scripts/compile_events.py

reset-mem0-graph:
  uv run memory_bench/scripts/mem0_to_graph.py reset \
    --state-db memory_bench/state/graphify/state.sqlite \
    --out-dir memory_bench/logs/replay_mem0/graphify \
    --reset-output

mem0-to-graph:
  latest_export=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0) && \
  uv run memory_bench/scripts/mem0_to_graph.py add \
    --input "$latest_export" \
    --out-dir memory_bench/logs/replay_mem0/graphify \
    --state-db memory_bench/state/graphify/state.sqlite \
    --prefix graph

mem0-graph-to-cypher:
  nodes=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0/graphify --glob "graph_nodes_*.jsonl") && \
  edges=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0/graphify --glob "graph_edges_*.jsonl") && \
  uv run memory_bench/scripts/graph_to_cypher.py \
    --nodes "$nodes" \
    --edges "$edges" \
    --out-dir memory_bench/logs/replay_mem0/graphify/neo4j \
    --prefix graph

clean-and-restart-neo4j:
  # 如果端口占用可以尝试调用
  rm -rf memory_bench/neo4j-data/
  sleep 3
  docker compose -f memory_bench/docker-compose.neo4j.yml down --remove-orphans
  rm -rf memory_bench/neo4j-data/mem0/data
  rm -rf memory_bench/neo4j-data/zep/data
  rm -rf memory_bench/neo4j-data/cognee/data
  docker compose -f memory_bench/docker-compose.neo4j.yml up -d

# =============================================================================
# Cleanup Recipes — 基础清理原语
# =============================================================================

clean-neo4j:
  # 清空 Neo4j 图数据（不重启容器，使用 Cypher DETACH DELETE）
  # 影响两条管线，共享同一个容器
  python memory_bench/scripts/neo4j_clear.py

clean-bench-logs:
  # 清理 bench logs（只影响离线管线的中间产物）
  rm -rf memory_bench/logs/

clean-bench-state:
  # 清理 bench state（checkpoint / state.sqlite，只影响离线管线）
  rm -rf memory_bench/state/

clean-bench-events:
  # 清理 bench events（离线管线中间产物）
  rm -rf memory_bench/data/events/

clean-bench-claims:
  # 清理 bench claims（离线管线中间产物）
  rm -rf memory_bench/data/claims/

# --- 实时管线清理 ---

clean-realtime:
  # 实时管线只依赖 Neo4j 和 mem0 的 qdrant storage
  # 清理 qdrant storage（mem0 本地持久化）+ Neo4j
  rm -rf memory_bench/state/qdrant_storage/
  just clean-neo4j

# --- 增量命令（去掉 --force，依赖脚本自身的增量检查）---

mem0-ingest:
  # 增量 ingest（依赖 checkpoint，不清理）
  uv run memory_bench/scripts/replay_mem0.py ingest

mem0-ingest-graph-store:
  # 增量 ingest，启用 mem0 原生 graph store（Neo4j）
  uv run memory_bench/scripts/replay_mem0.py ingest --graph-store neo4j

mem0-export:
  # 导出当前 mem0 快照
  uv run memory_bench/scripts/replay_mem0.py export

claimify-all:
  # 增量 claimify（依赖 by_conv/*.jsonl 存在则 skip）
  latest_export=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0 --glob "export_*.jsonl") && \
  uv run ./memory_bench/scripts/claimify_all.py --input "$latest_export" --workers 2

compile-claims:
  # 汇总 claims（增量，除非 --force）
  uv run ./memory_bench/scripts/compiled_claims.py

memory-item-to-cypher:
  just mem0-to-graph
  just mem0-graph-to-cypher

claim-items-to-cypher:
  uv run memory_bench/scripts/claims_to_graph.py add
  claim_nodes=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/claims/graphify --glob "claims_nodes_*.jsonl") && \
  claim_edges=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/claims/graphify --glob "claims_edges_*.jsonl") && \
  uv run memory_bench/scripts/graph_to_cypher.py \
    --nodes "$claim_nodes" \
    --edges "$claim_edges" \
    --out-dir memory_bench/logs/claims/graphify/neo4j \
    --prefix claims


export-neo4j-schema-docs:
  # 一次生成节点/关系 schema + 边 schema 文档（默认参数）
  uv run memory_bench/scripts/export_node_schema.py
  uv run memory_bench/scripts/export_edge_schema.py

neo4j-apply-cypher:
  # mem0 graph → mem0 容器
  constraints_file=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0/graphify/neo4j --glob "graph_constraints_*.cypher") && \
  import_file=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/replay_mem0/graphify/neo4j --glob "graph_import_*.cypher") && \
  uv run memory_bench/scripts/neo4j_apply_cypher.py mem0 \
    --constraints "$constraints_file" \
    --import-file "$import_file"
  # claims graph → mem0 容器
  claims_constraints=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/claims/graphify/neo4j --glob "claims_constraints_*.cypher") && \
  claims_import=$(uv run memory_bench/scripts/latest_file.py --export-dir memory_bench/logs/claims/graphify/neo4j --glob "claims_import_*.cypher") && \
  uv run memory_bench/scripts/neo4j_apply_cypher.py mem0 \
    --constraints "$claims_constraints" \
    --import-file "$claims_import"

mem0-rerun-add:
  just build-index
  just annotate-all
  just compile-events
  just mem0-ingest
  just mem0-export
  just claimify-all
  just compile-claims
  just memory-item-to-cypher
  just claim-items-to-cypher
  just neo4j-apply-cypher

mem0-rerun-graph-store:
  just build-index
  just annotate-all
  just compile-events
  just mem0-ingest-graph-store
  just mem0-export

mem0-run-from-graph-store:
  just clean-neo4j
  just clean-bench-state
  just clean-bench-claims
  just clean-bench-logs
  just mem0-rerun-graph-store

# =============================================================================
# 快速测试入口 — 从不同 LLM 调用点切入
# =============================================================================

mem0-run-from-annotate:
  # 从 annotate_all 开始（LLM #1：事件标注）
  # 清空所有 → 所有步骤都强制重跑
  just clean-neo4j
  just clean-bench-state
  just clean-bench-claims
  just clean-bench-events
  just clean-bench-logs
  just mem0-rerun-add

mem0-run-from-ingest:
  # 从 replay_mem0 ingest 开始（跳过 LLM #1 标注）
  # 保留 events → annotate-all 增量 skip
  # 清 state/claims/logs → ingest/export/claimify 全部重跑
  just clean-neo4j
  just clean-bench-state
  just clean-bench-claims
  just clean-bench-logs
  just mem0-rerun-add

mem0-run-from-claim:
  # 从 claimify_all 开始（LLM #3：claim 提取）
  # 保留 events + export → annotate/ingest/export 都增量 skip
  # 清 claims → claimify 及之后强制重跑
  just clean-neo4j
  just clean-bench-state
  just clean-bench-claims
  just mem0-rerun-add

mem0-run-real-time:
  # 实时管线：清理 + 启动 server
  just clean-realtime
  just memory-chat-server

# -- Local LLM translation ----------------------------------------------------

test-llm-translate server='http://127.0.0.1:12393':
  curl {{ server }}/translate/llm/health
  curl -X POST "{{ server }}/translate/llm" \
    -H "Content-Type: application/json" \
    -d '{ \
      "text": "Hello there. The rain finally stopped this afternoon, so I took a slow walk by the river and watched the lights come on one by one.", \
      "target_language": "ZH" \
    }'
  curl -X POST "{{ server }}/translate/llm" \
    -H "Content-Type: application/json" \
    -d '{ \
      "text": "今天下午的会议比预期更顺利，我们不仅确认了发布时间，还把后续两周的分工也一起敲定了。", \
      "target_language": "EN" \
    }'
  curl -X POST "{{ server }}/translate/llm" \
    -H "Content-Type: application/json" \
    -d '{ \
      "text": "それでは問題です。澄み渡った青空をゆく、そこに人がいたのなら間違いなく誰もが振り返り、ため息をこぼしてしまうほどの美貌の魔女は、いったい誰でしょう？", \
      "target_language": "ZH" \
    }'
  curl -X POST "{{ server }}/translate/llm" \
    -H "Content-Type: application/json" \
    -d '{ \
      "text": "La bibliotheque du quartier ferme un peu plus tot le vendredi, mais je passe encore en fin d apres-midi pour choisir un roman et lire pres de la fenetre.", \
      "target_language": "ZH" \
    }'

test-embedding server='http://127.0.0.1:12393':
  curl -X POST "{{ server }}/v1/embeddings" \
    -H "Content-Type: application/json" \
    -d '{ \
      "model": "bge-m3", \
      "input": ["hello world", "今天下午一起去散步吧"] \
    }'

qwen-tts-batch input='data/qwen_tts_batch_input.txt' output_dir='output/qwen_tts_batch' server='http://127.0.0.1:12393' profile='' emotion='default' ref_audio_path='' ref_text='':
  uv run python scripts/qwen_tts_batch_generate.py --input {{ input }} --output-dir {{ output_dir }} --server {{ server }} {{ if profile != '' { '--profile ' + profile } else { '' } }} {{ if emotion != '' { '--emotion ' + emotion } else { '' } }} {{ if ref_audio_path != '' { '--ref-audio-path ' + ref_audio_path } else { '' } }} {{ if ref_text != '' { '--ref-text ' + ref_text } else { '' } }}

qwen-tts-batch-prune input='data/qwen_tts_batch_input.txt' output_dir='output/qwen_tts_batch' server='http://127.0.0.1:12393' profile='' emotion='default' ref_audio_path='' ref_text='':
  uv run python scripts/qwen_tts_batch_generate.py --input {{ input }} --output-dir {{ output_dir }} --server {{ server }} --prune-stale {{ if profile != '' { '--profile ' + profile } else { '' } }} {{ if emotion != '' { '--emotion ' + emotion } else { '' } }} {{ if ref_audio_path != '' { '--ref-audio-path ' + ref_audio_path } else { '' } }} {{ if ref_text != '' { '--ref-text ' + ref_text } else { '' } }}

qwen-tts-batch-help:
  uv run python scripts/qwen_tts_batch_generate.py --help
