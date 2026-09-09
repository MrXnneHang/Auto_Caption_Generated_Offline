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

test-light:
  uv run pytest tests/test_lightweight_runtime.py tests/test_config_version.py tests/test_tool_prompt_cleanup.py tests/test_asr_client_fallback.py

test-voice-contract:
  uv run pytest tests/test_lightweight_runtime.py

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
  uv run ty check --error-on-warning
  uv run ruff check . --exclude packages --exclude .git --exclude justfile --exclude models

fmt-docs:
  prettier --ignore-path .prettierignore --write '**/*.md'

test:
  uv run pytest tests -vvv

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
