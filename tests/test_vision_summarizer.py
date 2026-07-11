"""验证单图 vision summary 的 JSON 解析约束。"""

from __future__ import annotations

import json

from lab.agent.agents.memory_agent.vision_summarizer import VisionSummarizer


def test_parse_single_summary_json_accepts_rich_schema_with_scene_and_summary() -> None:
    """验证单图解析允许携带额外结构化字段。

    验证点：
    - 只要顶层同时存在非空的 scene 和 summary，就接受该 JSON。
    - 额外字段不会影响 brief 的提取。
    """
    raw = json.dumps(
        {
            "scene": "编辑器与终端同屏",
            "summary": "画面主体是代码编辑器，底部有终端输出，左侧有文件树。",
            "key_items": [
                {"type": "app", "label": "VS Code", "detail": "深色主题"},
                {"type": "ui", "label": "文件树", "detail": "左侧展开"},
                {"type": "ui", "label": "终端", "detail": "底部有日志"},
            ],
            "visible_text": ["run_tool_loop"],
            "ui_hints": ["顶部有多个标签"],
            "uncertainty": [],
        },
        ensure_ascii=False,
    )

    parsed = VisionSummarizer._parse_single_summary_json(raw)

    assert parsed == (raw, "编辑器与终端同屏")


def test_parse_single_summary_json_accepts_missing_summary() -> None:
    """验证缺少 summary 时仍可解析（新精简 prompt 不要求 summary 字段）。"""
    raw = json.dumps({"scene": "编辑器与终端同屏"}, ensure_ascii=False)

    parsed = VisionSummarizer._parse_single_summary_json(raw)

    assert parsed is not None
    assert parsed[1] == "编辑器与终端同屏"


def test_parse_single_summary_json_rejects_overlong_summary() -> None:
    """验证顶层 summary 过长时会被拒绝。"""
    raw = json.dumps(
        {
            "scene": "编辑器与终端同屏",
            "summary": "a" * 401,
        },
        ensure_ascii=False,
    )

    parsed = VisionSummarizer._parse_single_summary_json(raw)

    assert parsed is None


def test_parse_single_summary_json_strips_markdown_fence() -> None:
    """验证模型输出被 markdown fence 包裹时仍能正确解析。"""
    inner = json.dumps(
        {"scene": "桌面截图", "brief": "用户在浏览网页", "ocr": ["pixiv"]},
        ensure_ascii=False,
    )

    # ```json ... ```
    wrapped = f"```json\n{inner}\n```"
    parsed = VisionSummarizer._parse_single_summary_json(wrapped)
    assert parsed is not None
    assert parsed[1] == "用户在浏览网页"

    # ```` (4 backticks)
    wrapped4 = f"````json\n{inner}\n````"
    parsed4 = VisionSummarizer._parse_single_summary_json(wrapped4)
    assert parsed4 is not None

    # bare ``` without language tag
    bare = f"```\n{inner}\n```"
    parsed_bare = VisionSummarizer._parse_single_summary_json(bare)
    assert parsed_bare is not None
