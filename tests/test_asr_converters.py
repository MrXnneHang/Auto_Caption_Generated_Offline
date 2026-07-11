from __future__ import annotations

import pytest

from lab.asr.converter import convert_asr_response_to_sentences, rewrite_sentence_text_by_words
from lab.asr.qwen_asr.engine import parse_qwen_asr_output


def test_funasr_converter_split_sentence_on_gap_and_rewrite_text() -> None:
    input_data = {
        "key": "demo",
        "text": "\u4f60 \u597d world",
        "timestamp": [[0, 900], [900, 1999], [2700, 3500]],
    }

    sentences = convert_asr_response_to_sentences(input_data)

    assert len(sentences) == 2
    assert sentences[0]["text"] == "\u4f60\u597d"
    assert sentences[0]["start"] == 0
    assert sentences[0]["end"] == 1999
    assert sentences[0]["Words"] == [
        {"text": "\u4f60", "start": 0, "end": 900},
        {"text": "\u597d", "start": 900, "end": 1999},
    ]
    assert sentences[1]["text"] == "world"
    assert sentences[1]["start"] == 2700
    assert sentences[1]["end"] == 3500


def test_funasr_converter_raises_on_mismatched_text_and_timestamps() -> None:
    input_data = {
        "key": "demo",
        "text": "\u4f60 \u597d",
        "timestamp": [[0, 1]],
    }

    with pytest.raises(AssertionError):
        convert_asr_response_to_sentences(input_data)


def test_rewrite_sentence_text_by_words_spacing_rule() -> None:
    words = [
        {"text": "\u4f60", "start": 0, "end": 1},
        {"text": "\u597d", "start": 1, "end": 2},
        {"text": "inspired", "start": 2, "end": 3},
        {"text": "by", "start": 3, "end": 4},
        {"text": "\u5fb7", "start": 4, "end": 5},
        {"text": "\u56fd", "start": 5, "end": 6},
    ]

    assert rewrite_sentence_text_by_words(words) == "\u4f60\u597d inspired by \u5fb7\u56fd"


def test_qwen_parser_uses_native_timestamp_tags() -> None:
    raw_output = "language Chinese<asr_text><|0.00|>\u4f60<|0.50|>\u597d<|1.00|> world<|2.00|>"

    text, timestamps = parse_qwen_asr_output(raw_output, audio_duration_ms=2000)

    assert text == "\u4f60 \u597d world"
    assert timestamps == [[0, 500], [500, 1000], [1000, 2000]]

    sentences = convert_asr_response_to_sentences(
        {
            "key": "demo",
            "text": text,
            "timestamp": timestamps,
        }
    )
    assert sentences[0]["text"] == "\u4f60\u597d world"


def test_qwen_parser_falls_back_when_timestamp_tags_are_missing() -> None:
    raw_output = "language English<asr_text>hello world"

    text, timestamps = parse_qwen_asr_output(raw_output, audio_duration_ms=1200)

    assert text == "hello world"
    assert timestamps == [[0, 600], [600, 1200]]
