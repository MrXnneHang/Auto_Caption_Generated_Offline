"""本地假 OpenAI /v1/embeddings 端点：memU keyless smoke 用。

确定性向量：字符 bigram 袋哈希到固定维度再 L2 归一——同一文本恒同向量，且有字面
重叠的文本有正相似度（够 smoke 验证 commit → retrieve 的排序管线，无需任何外部 key）。

用法：
    uv run python scripts/memu_mock_embeddings.py --port 8901
然后把 MEMU_BASE_URL 指到 http://127.0.0.1:8901/v1（见 docs/guide/architecture/memu-memory.md）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_DIMS = 64


def embed_text(text: str) -> list[float]:
    """字符 bigram 袋 → 固定维度计数 → L2 归一。空文本给全零外的稳定向量。"""
    vec = [0.0] * _DIMS
    padded = f"^{text}$"
    for i in range(len(padded) - 1):
        bigram = padded[i : i + 2].encode("utf-8")
        dim = int.from_bytes(hashlib.sha256(bigram).digest()[:4], "big") % _DIMS
        vec[dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # http.server 命名约定
        if not self.path.rstrip("/").endswith("/embeddings"):
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(body or b"{}")
        raw = payload.get("input", [])
        inputs = [raw] if isinstance(raw, str) else list(raw)
        data = [
            {"object": "embedding", "index": i, "embedding": embed_text(str(text))} for i, text in enumerate(inputs)
        ]
        response = json.dumps(
            {
                "object": "list",
                "data": data,
                "model": payload.get("model", "mock-embedding"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:  # 基类签名如此
        pass  # 安静：smoke 输出只看 memu 侧


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock OpenAI-compatible /v1/embeddings for memU smoke tests")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"mock embeddings on http://127.0.0.1:{args.port}/v1 (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
