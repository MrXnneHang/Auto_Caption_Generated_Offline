"""按日期分片的 JSON 历史存储实现。

该模块负责把对话轮次持久化到按日期命名的 JSON 文件中，供
`/memory/chat` 等链路复用，也避免与 runtime 层的 `lab.conversations`
职责混淆。

目录结构示例::

    conversations/
        2026-03-03.json
        2026-03-04.json
        ...

单个文件内容示例::

    [
        {"role": "user", "content": "...", "timestamp": "..."},
        {"role": "assistant", "content": "...", "timestamp": "..."}
    ]

使用示例::

    from lab.history_storage.store import HistoryStorage

    store = HistoryStorage(base_dir="conversations")
    messages = store.read_conversation("2026-03-03")
    store.append_turn("2026-03-03", role="user", content="Hello")
    store.append_turn("2026-03-03", role="assistant", content="Hi there!")
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger


class HistoryStorage:
    """按日期保存会话历史的持久化存储。"""

    def __init__(self, base_dir: str = "conversations") -> None:
        """初始化历史存储目录。

        Args:
            base_dir: 用于保存 JSON 历史文件的目录。
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log = logger.bind(group="history_storage")

    def _get_file_path(self, date_id: str) -> Path:
        """根据日期 ID 生成目标文件路径。

        Args:
            date_id: 日期字符串，例如 `2026-03-03`，也支持自定义后缀 ID。

        Returns:
            对应的 JSON 文件路径。
        """
        return self.base_dir / f"{date_id}.json"

    def read_conversation(self, date_id: str) -> list[dict[str, str]]:
        """读取某个日期 ID 对应的历史消息列表。

        Args:
            date_id: 日期字符串或自定义历史 ID。

        Returns:
            历史消息列表；如果文件不存在或损坏，则返回空列表。
        """
        file_path = self._get_file_path(date_id)

        if not file_path.exists():
            self.log.info("No history file for %s (new conversation)", date_id)
            return []

        try:
            with file_path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            self.log.warning("Corrupted history file %s: %s", date_id, exc)
            return []
        except Exception as exc:
            self.log.error("Failed to read history %s: %s", date_id, exc)
            return []

        messages: list[dict[str, str]] = data  # type: ignore[assignment]
        self.log.info("Loaded %d messages from %s", len(messages), date_id)
        return messages

    def append_turn(
        self,
        date_id: str,
        role: str,
        content: str,
        extra: dict[str, str] | None = None,
    ) -> None:
        """向指定日期的历史文件追加一条消息。

        Args:
            date_id: 日期字符串或自定义历史 ID。
            role: 消息角色，例如 `user` 或 `assistant`。
            content: 消息正文。
            extra: 需要额外写入的字段。
        """
        file_path = self._get_file_path(date_id)
        messages = self.read_conversation(date_id) if file_path.exists() else []

        message: dict[str, str] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        if extra:
            message.update(extra)

        messages.append(message)

        try:
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            self.log.info("Appended %s turn to %s (total: %d messages)", role, date_id, len(messages))
        except Exception as exc:
            self.log.error("Failed to write history %s: %s", date_id, exc)
            raise

    def list_conversations(self) -> list[str]:
        """列出当前目录下所有可用的历史 ID。"""
        if not self.base_dir.exists():
            return []

        return sorted(file.stem for file in self.base_dir.glob("*.json"))

    def get_today_id(self) -> str:
        """获取当前 UTC 日期对应的历史 ID。"""
        return datetime.now(UTC).strftime("%Y-%m-%d")


# 为低风险迁移保留旧名字。
ConversationStore = HistoryStorage
