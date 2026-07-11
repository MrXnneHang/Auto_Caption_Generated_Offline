from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _emit(event: str, target: str, status: str, message: str, current: int, total: int) -> None:
    payload: dict[str, object] = {
        "event": event,
        "target": target,
        "status": status,
        "message": message,
        "progressCurrent": current,
        "progressTotal": total,
        "progressUnit": "stage",
    }
    print(json.dumps({"kind": "event", "payload": payload}), flush=True)


@dataclass
class _MsStep:
    model_id: str
    local_dir: str
    files: list[str] = field(default_factory=list)


_TARGETS: dict[str, list[_MsStep]] = {
    "genie-base": [
        _MsStep("xnnehang/xnnehanglab-geniedata", "models/GenieData"),
    ],
    "gsv-lite": [
        _MsStep("pengzhendong/chinese-hubert-base", "models/GSVLiteData/chinese-hubert-base"),
        _MsStep(
            "dienstag/chinese-roberta-wwm-ext-large",
            "models/GSVLiteData/chinese-roberta-wwm-ext-large",
            files=[
                "pytorch_model.bin",
                "added_tokens.json",
                "config.json",
                "configuration.json",
                "README.md",
                "special_tokens_map.json",
                "tokenizer_config.json",
                "tokenizer.json",
            ],
        ),
        _MsStep("xnnehang/gsv-v2proplus-g2p-resource", "models/GSVLiteData/g2p"),
        _MsStep("xnnehang/gsv-v2proplus-sv-resource", "models/GSVLiteData/sv"),
    ],
    "luming-genie-tts-v2-pro-plus": [
        _MsStep("xnnehang/luming-genie-tts-v2-pro-plus", "models/genie-tts/luming-v2-pro-plus"),
    ],
    "gsv-baoqiao": [
        _MsStep("xnnehang/luming-gpt-sovits-v2-pro-plus", "models/gsv-tts-lite/luming-v2-pro-plus"),
    ],
    "qwen-tts-0.6b": [
        _MsStep("Qwen/Qwen3-TTS-12Hz-0.6B-Base", "models/Qwen3-TTS-12Hz-0.6B-Base"),
    ],
    "qwen-tts-1.7b": [
        _MsStep("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "models/Qwen3-TTS-12Hz-1.7B-Base"),
    ],
    "sherpa-paraformer": [
        _MsStep("xnnehang/sherpa-onnx-paraformer-zh-2023-09-14", "models/sherpa-onnx-paraformer-zh-2023-09-14"),
    ],
    "silero-vad": [
        _MsStep("xnnehang/k2-fsa-silero-vad", "models", files=["silero_vad.onnx"]),
    ],
    "local-embedding": [
        _MsStep("ggml-org/bge-m3-Q8_0-GGUF", "models", files=["bge-m3-q8_0.gguf"]),
    ],
    "llm-translate": [
        _MsStep("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "models", files=["qwen2.5-0.5b-instruct-q8_0.gguf"]),
    ],
}


def _run_step(step: _MsStep, workspace_root: Path) -> None:
    local_dir = workspace_root / step.local_dir
    local_dir.mkdir(parents=True, exist_ok=True)

    if step.files:
        from modelscope.hub.file_download import model_file_download

        for filename in step.files:
            model_file_download(model_id=step.model_id, file_path=filename, local_dir=str(local_dir))
    else:
        from modelscope.hub.snapshot_download import snapshot_download

        snapshot_download(model_id=step.model_id, local_dir=str(local_dir))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="XnneHangLab model downloader")
    parser.add_argument("target", help="Download target key")
    args = parser.parse_args()
    target: str = args.target

    steps = _TARGETS.get(target)
    if steps is None:
        _emit("download.failed", target, "failed", f"Unknown download target: {target!r}", 0, 1)
        sys.exit(1)

    workspace_root = Path.cwd()
    total = len(steps) + 1

    _emit("download.started", target, "queued", f"准备下载 {target}", 0, total)

    for i, step in enumerate(steps, start=1):
        _emit("download.progress", target, "downloading", step.model_id, i - 1, total)
        try:
            _run_step(step, workspace_root)
        except Exception as exc:
            _emit("download.failed", target, "failed", str(exc), i - 1, total)
            sys.exit(1)

    _emit("download.completed", target, "completed", f"{target} 下载完成", total, total)


if __name__ == "__main__":
    main()
