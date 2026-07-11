# copyright@https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, overload

import pysbd
from langdetect import detect
from loguru import logger

from lab.agent.output_types import AudioOutput, ToolCallEvent
from lab.utils.text_cleaner import CleanerConfig, TextCleaner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


ABBREVIATIONS = [
    "Mr.",
    "Mrs.",
    "Dr.",
    "Prof.",
    "Inc.",
    "Ltd.",
    "Jr.",
    "Sr.",
    "e.g.",
    "i.e.",
    "vs.",
    "St.",
    "Rd.",
]
COMMAS = [",", ";", "\u3001", "\uff0c", "\uff1b"]
END_PUNCTUATIONS = [".", "!", "?", "\u3002", "\uff01", "\uff1f", "...", "\u2026\u2026"]
SENTENCE_END_CHARS = {".", "!", "?", "\u3002", "\uff01", "\uff1f"}
TRAILING_SENTENCE_CHARS = set("\"'”’)]}>\u300d\u300f\u3011\uff09")
SECONDARY_SPLIT_CHARS = {",", ";", "\u3001", "\uff0c", "\uff1b", ":", "\uff1a"}
SHORT_SENTENCE_EDGE_CHARS = "\"'”’“‘()[]{}<>（）【】「」『』"
SHORT_SENTENCE_TRAILING_CHARS = ".,!?;:。！？；：…~，、"
SHORT_SENTENCE_THRESHOLD = 5
PREFERRED_SENTENCE_LEN_RANGE = (10, 15)
LIST_MARKER_RE = re.compile(r"(^|[\s\[\(\{\]\)\}])\d+\.$")
FRAGILE_DOT_RE = re.compile(r"(?<!\S)\d+\.(?=\s*\S)|[A-Za-z0-9_/-]+(?:\.[A-Za-z0-9_/-]+)+")
PARAGRAPH_BREAK_RE = re.compile(r"(?:\r?\n\s*){2,}")
ACTION_LINE_BREAK_RE = re.compile(r"\r?\n\s*(?:\[[^\]\r\n]+\]|\([^)]+\))")
FULL_BLOCK_BREAK_RE = re.compile(r"\r?\n+")
URL_TEXT_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\u3000]+")
CONTROL_TAG_RE = re.compile(r"\[\s*(tts|ts|expression)\s*:\s*([^\]\r\n]+?)\s*\]", re.IGNORECASE)
CONTROL_TAG_PREFIXES = ("[tts", "[ts", "[expression")
DEFAULT_STREAMING_CLEANER = TextCleaner(
    CleanerConfig(
        clean_emoji=False,
        clean_markdown=False,
        normalize_whitespace=True,
    )
)

# Set of languages directly supported by pysbd
SUPPORTED_LANGUAGES = {
    "am",
    "ar",
    "bg",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fa",
    "fr",
    "hi",
    "hy",
    "it",
    "ja",
    "kk",
    "mr",
    "my",
    "nl",
    "pl",
    "ru",
    "sk",
    "ur",
    "zh",
}


def detect_language(text: str) -> str | None:
    try:
        detected = detect(text)
        return detected if detected in SUPPORTED_LANGUAGES else None
    except Exception as exc:
        logger.debug(f"Language detection failed, language not supported by pysbd: {exc}")
        return None


def is_complete_sentence(text: str) -> bool:
    text = text.strip()
    if not text:
        return False

    if any(text.endswith(abbrev) for abbrev in ABBREVIATIONS):
        return False

    idx = len(text) - 1
    while idx >= 0 and text[idx] in TRAILING_SENTENCE_CHARS:
        idx -= 1
    if idx < 0:
        return False
    return _boundary_token_length(text, idx) > 0


def contains_comma(text: str) -> bool:
    return any(comma in text for comma in COMMAS)


def comma_splitter(text: str) -> tuple[str, str]:
    if not text:
        return "", ""

    for comma in COMMAS:
        if comma in text:
            split_text = text.split(comma, 1)
            return split_text[0].strip() + comma, split_text[1].strip()
    return text, ""


def has_punctuation(text: str) -> bool:
    return contains_comma(text) or contains_end_punctuation(text)


def contains_end_punctuation(text: str) -> bool:
    return _find_first_sentence_boundary(text) is not None


def _next_non_space_index(text: str, start: int) -> int | None:
    for idx in range(start, len(text)):
        if not text[idx].isspace():
            return idx
    return None


def _looks_like_abbreviation(text: str, period_idx: int) -> bool:
    probe = text[max(0, period_idx - 12) : period_idx + 1].lower()
    return any(probe.endswith(abbrev.lower()) for abbrev in ABBREVIATIONS)


def _is_inline_period(text: str, idx: int) -> bool:
    if text[idx] != ".":
        return False

    if _looks_like_abbreviation(text, idx):
        return True

    prev_char = text[idx - 1] if idx > 0 else ""
    immediate_next = text[idx + 1] if idx + 1 < len(text) else ""
    next_idx = _next_non_space_index(text, idx + 1)

    if prev_char.isdigit() and next_idx is None:
        return True

    if prev_char.isalnum() and immediate_next.isalnum():
        return True

    number_start = idx
    while number_start > 0 and text[number_start - 1].isdigit():
        number_start -= 1
    marker_candidate = text[max(0, number_start - 1) : idx + 1]
    if LIST_MARKER_RE.fullmatch(marker_candidate):
        return True

    return False


def _boundary_token_length(text: str, idx: int) -> int:
    if idx < 0 or idx >= len(text):
        return 0

    if text.startswith("...", idx):
        return 3
    if text.startswith("\u2026\u2026", idx):
        return 2

    char = text[idx]
    if char not in SENTENCE_END_CHARS:
        return 0
    if char == "." and _is_inline_period(text, idx):
        return 0
    return 1


def _find_first_sentence_boundary(text: str) -> int | None:
    for idx in range(len(text)):
        if _boundary_token_length(text, idx) > 0:
            return idx
    return None


def _find_structural_boundary(text: str) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []

    for pattern in (PARAGRAPH_BREAK_RE, ACTION_LINE_BREAK_RE):
        match = pattern.search(text)
        if match and text[: match.start()].strip():
            candidates.append(match.span())

    if not candidates:
        return None

    return min(candidates, key=lambda span: span[0])


def segment_text_by_rules(text: str) -> tuple[list[str], str]:
    if not text:
        return [], ""

    complete_sentences: list[str] = []
    start = 0
    idx = 0

    while idx < len(text):
        token_len = _boundary_token_length(text, idx)
        if token_len == 0:
            idx += 1
            continue

        end = idx + token_len
        while end < len(text) and text[end] in TRAILING_SENTENCE_CHARS:
            end += 1

        sentence = text[start:end].strip()
        if sentence:
            complete_sentences.append(sentence)

        start = end
        while start < len(text) and text[start].isspace():
            start += 1
        idx = start

    remaining = text[start:].strip()
    return complete_sentences, remaining


def segment_text_by_regex(text: str) -> tuple[list[str], str]:
    return segment_text_by_rules(text)


def segment_text_by_pysbd(text: str) -> tuple[list[str], str]:
    if not text:
        return [], ""

    if FRAGILE_DOT_RE.search(text):
        return segment_text_by_rules(text)

    try:
        lang = detect_language(text)
        if lang is None:
            return segment_text_by_regex(text)

        segmenter = pysbd.Segmenter(language=lang, clean=False)
        sentences = segmenter.segment(text)
        if not sentences:
            return [], text

        complete_sentences: list[str] = []
        for sent in sentences[:-1]:
            sent = sent.strip()
            if sent:
                complete_sentences.append(sent)

        last_sent = sentences[-1].strip()
        if is_complete_sentence(last_sent):
            complete_sentences.append(last_sent)
            remaining = ""
        else:
            remaining = last_sent

        if any(len(sent) <= 2 and contains_end_punctuation(sent) for sent in complete_sentences):
            return segment_text_by_rules(text)

        logger.debug(f"Processed sentences: {complete_sentences}, Remaining: {remaining}")
        return complete_sentences, remaining
    except Exception as exc:
        logger.error(f"Error in sentence segmentation: {exc}")
        return segment_text_by_rules(text)


def _normalize_paragraph(paragraph: str) -> str:
    return re.sub(r"\s*\n\s*", " ", paragraph).strip()


def _split_long_sentence(sentence: str, max_sentence_len: int) -> list[str]:
    sentence = sentence.strip()
    if not sentence:
        return []
    if max_sentence_len <= 0 or len(sentence) <= max_sentence_len:
        return [sentence]
    if URL_TEXT_RE.search(sentence):
        return [sentence]

    parts: list[str] = []
    remaining = sentence

    while len(remaining) > max_sentence_len:
        split_idx = max((remaining.rfind(char, 0, max_sentence_len + 1) for char in SECONDARY_SPLIT_CHARS), default=-1)
        if split_idx <= 0:
            split_idx = min(
                (
                    idx
                    for idx, char in enumerate(remaining[max_sentence_len:], start=max_sentence_len)
                    if char in SECONDARY_SPLIT_CHARS
                ),
                default=-1,
            )
        if split_idx <= 0:
            break

        piece = remaining[: split_idx + 1].strip()
        if not piece:
            break
        parts.append(piece)
        remaining = remaining[split_idx + 1 :].lstrip()

    if remaining:
        parts.append(remaining.strip())

    return [part for part in parts if part]


def _effective_sentence_length(text: str) -> int:
    compact = re.sub(r"\s+", "", text.strip())
    compact = compact.strip(SHORT_SENTENCE_EDGE_CHARS)
    compact = compact.rstrip(SHORT_SENTENCE_TRAILING_CHARS)
    compact = compact.strip(SHORT_SENTENCE_EDGE_CHARS)
    return len(compact)


def _should_merge_short_sentence(text: str) -> bool:
    candidate = text.strip()
    if not candidate:
        return False

    if FRAGILE_DOT_RE.search(candidate):
        return False

    if LIST_MARKER_RE.search(candidate):
        return False

    return _effective_sentence_length(candidate) <= SHORT_SENTENCE_THRESHOLD


def _sentence_merge_score(text: str) -> tuple[float, float]:
    low, high = PREFERRED_SENTENCE_LEN_RANGE
    length = _effective_sentence_length(text)
    if low <= length <= high:
        penalty = 0.0
    elif length < low:
        penalty = float(low - length)
    else:
        penalty = float(length - high)
    midpoint = (low + high) / 2
    return penalty, abs(length - midpoint)


def _within_sentence_length_limit(text: str, max_sentence_len: int) -> bool:
    if max_sentence_len <= 0:
        return True
    return _effective_sentence_length(text) <= max_sentence_len


def _merge_short_sentence_texts(
    texts: list[str],
    *,
    hold_trailing_short: bool = False,
    max_sentence_len: int = 0,
) -> tuple[list[str], str]:
    pending = [text.strip() for text in texts if text.strip()]
    merged: list[str] = []
    trailing_short = ""

    index = 0
    while index < len(pending):
        candidate = pending[index]
        if not _should_merge_short_sentence(candidate):
            merged.append(candidate)
            index += 1
            continue

        has_prev = bool(merged)
        has_next = index + 1 < len(pending)

        if has_prev and has_next:
            previous_merged = f"{merged[-1]}{candidate}"
            next_merged = f"{candidate}{pending[index + 1]}"
            previous_allowed = _within_sentence_length_limit(previous_merged, max_sentence_len)
            next_allowed = _within_sentence_length_limit(next_merged, max_sentence_len)
            if previous_allowed and next_allowed:
                if _sentence_merge_score(previous_merged) <= _sentence_merge_score(next_merged):
                    merged[-1] = previous_merged
                else:
                    pending[index + 1] = next_merged
            elif previous_allowed:
                merged[-1] = previous_merged
            elif next_allowed:
                pending[index + 1] = next_merged
            else:
                merged.append(candidate)
            index += 1
            continue

        if has_next:
            next_merged = f"{candidate}{pending[index + 1]}"
            if _within_sentence_length_limit(next_merged, max_sentence_len):
                pending[index + 1] = next_merged
            else:
                merged.append(candidate)
            index += 1
            continue

        if hold_trailing_short:
            trailing_short = f"{trailing_short}{candidate}" if trailing_short else candidate
        elif has_prev and _within_sentence_length_limit(f"{merged[-1]}{candidate}", max_sentence_len):
            merged[-1] = f"{merged[-1]}{candidate}"
        else:
            merged.append(candidate)
        index += 1

    return merged, trailing_short


def _segment_with_method(text: str, segment_method: str) -> tuple[list[str], str]:
    if segment_method == "regex":
        return segment_text_by_regex(text)
    return segment_text_by_pysbd(text)


def _segment_document(
    text: str,
    *,
    max_sentence_len: int,
    segment_method: str,
    include_incomplete_tail: bool,
) -> tuple[list[str], str]:
    if not text.strip():
        return [], ""

    paragraphs = [part for part in PARAGRAPH_BREAK_RE.split(text) if part.strip()]
    sentences: list[str] = []
    trailing_fragment = ""

    for index, paragraph in enumerate(paragraphs):
        normalized = _normalize_paragraph(paragraph)
        if not normalized:
            continue

        paragraph_sentences, remaining = _segment_with_method(normalized, segment_method)
        for sentence in paragraph_sentences:
            sentences.extend(_split_long_sentence(sentence, max_sentence_len))

        is_last_paragraph = index == len(paragraphs) - 1
        if not remaining.strip():
            continue

        if is_last_paragraph and not include_incomplete_tail:
            trailing_fragment = remaining.strip()
        else:
            sentences.extend(_split_long_sentence(remaining, max_sentence_len))

    return [sentence for sentence in sentences if sentence.strip()], trailing_fragment


def segment_full(
    text: str,
    cleaner: TextCleaner | None = None,
    max_sentence_len: int = 100,
    segment_method: str = "pysbd",
) -> list[str]:
    active_cleaner = cleaner or TextCleaner()
    cleaned = active_cleaner.clean(text)
    blocks = [block.strip() for block in FULL_BLOCK_BREAK_RE.split(cleaned) if block.strip()]
    if not blocks:
        return []

    results: list[str] = []
    for block in blocks:
        sentences, trailing_fragment = _segment_document(
            block,
            max_sentence_len=max_sentence_len,
            segment_method=segment_method,
            include_incomplete_tail=True,
        )
        if trailing_fragment.strip():
            sentences.extend(_split_long_sentence(trailing_fragment, max_sentence_len))
        merged_sentences, trailing_short = _merge_short_sentence_texts(
            sentences,
            max_sentence_len=max_sentence_len,
        )
        if trailing_short:
            merged_sentences.append(trailing_short)
        results.extend(sentence for sentence in merged_sentences if sentence.strip())
    return results


class TagState(Enum):
    START = "start"
    INSIDE = "inside"
    END = "end"
    SELF_CLOSING = "self"
    NONE = "none"


@dataclass
class TagInfo:
    name: str
    state: TagState

    def __str__(self) -> str:
        if self.state == TagState.NONE:
            return "none"
        return f"{self.name}:{self.state.value}"


@dataclass
class ControlTags:
    tts_emotion_key: str | None = None
    expression_emotion_key: str | None = None

    def is_empty(self) -> bool:
        return self.tts_emotion_key is None and self.expression_emotion_key is None

    def copy(self) -> ControlTags:
        return ControlTags(
            tts_emotion_key=self.tts_emotion_key,
            expression_emotion_key=self.expression_emotion_key,
        )

    def render_prefix(self) -> str:
        parts: list[str] = []
        if self.tts_emotion_key is not None:
            parts.append(f"[tts:{self.tts_emotion_key}]")
        if self.expression_emotion_key is not None:
            parts.append(f"[expression:{self.expression_emotion_key}]")
        return "".join(parts)


@dataclass
class SentenceWithTags:
    text: str
    tags: list[TagInfo]
    control_tags: ControlTags = field(default_factory=ControlTags)


class SentenceDivider:
    def __init__(
        self,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        valid_tags: list[str] | None = None,
        cleaner: TextCleaner | None = None,
        max_sentence_len: int = 100,
        stream_min_sentences: int = 2,
    ):
        self.faster_first_response = faster_first_response
        self.segment_method = segment_method
        self.valid_tags = valid_tags or ["think"]
        self.cleaner = cleaner or DEFAULT_STREAMING_CLEANER
        self.max_sentence_len = max_sentence_len
        self.stream_min_sentences = max(1, stream_min_sentences)
        self._is_first_sentence = True
        self._buffer = ""
        self._tag_stack: list[TagInfo] = []
        self._pending_control_tags = ControlTags()
        self._full_response: list[str] = []

    def _get_current_tags(self) -> list[TagInfo]:
        return [TagInfo(tag.name, TagState.INSIDE) for tag in self._tag_stack]

    def _extract_tag(self, text: str) -> tuple[TagInfo | None, str]:
        first_tag = None
        first_pos = len(text)
        tag_type = None
        matched_tag = None

        for tag in self.valid_tags:
            pattern = f"<{tag}/>"
            match = re.search(pattern, text)
            if match and match.start() < first_pos:
                first_pos = match.start()
                first_tag = match
                tag_type = TagState.SELF_CLOSING
                matched_tag = tag

        for tag in self.valid_tags:
            pattern = f"<{tag}>"
            match = re.search(pattern, text)
            if match and match.start() < first_pos:
                first_pos = match.start()
                first_tag = match
                tag_type = TagState.START
                matched_tag = tag

        for tag in self.valid_tags:
            pattern = f"</{tag}>"
            match = re.search(pattern, text)
            if match and match.start() < first_pos:
                first_pos = match.start()
                first_tag = match
                tag_type = TagState.END
                matched_tag = tag

        if not first_tag or tag_type is None or matched_tag is None:
            return None, text

        if tag_type == TagState.START:
            self._tag_stack.append(TagInfo(matched_tag, TagState.START))
        elif tag_type == TagState.END:
            if not self._tag_stack or self._tag_stack[-1].name != matched_tag:
                logger.warning(f"Mismatched closing tag: {matched_tag}")
            else:
                self._tag_stack.pop()

        return TagInfo(matched_tag, tag_type), text[first_tag.end() :].lstrip()

    def _find_next_tag_pos(self) -> int:
        next_tag_pos = len(self._buffer)
        for tag in self.valid_tags:
            for pattern in (f"<{tag}>", f"</{tag}>", f"<{tag}/>"):
                pos = self._buffer.find(pattern)
                if pos != -1 and pos < next_tag_pos:
                    next_tag_pos = pos
        return next_tag_pos

    def _default_tags(self) -> list[TagInfo]:
        return self._get_current_tags() or [TagInfo("", TagState.NONE)]

    def _merge_pending_control_tags(self, controls: ControlTags) -> None:
        if controls.tts_emotion_key is not None:
            self._pending_control_tags.tts_emotion_key = controls.tts_emotion_key
        if controls.expression_emotion_key is not None:
            self._pending_control_tags.expression_emotion_key = controls.expression_emotion_key

    def _take_pending_control_tags(self) -> ControlTags:
        controls = self._pending_control_tags.copy()
        self._pending_control_tags = ControlTags()
        return controls

    def _extract_leading_control_tags(self, text: str) -> tuple[ControlTags | None, str, bool]:
        index = 0
        consumed_any = False
        controls = ControlTags()

        while True:
            while index < len(text) and text[index].isspace():
                index += 1

            if index >= len(text) or text[index] != "[":
                break

            match = CONTROL_TAG_RE.match(text, index)
            if match is None:
                remainder = text[index:].lower()
                if remainder.startswith(CONTROL_TAG_PREFIXES):
                    return controls if consumed_any else None, text, True
                break

            control_type = match.group(1).lower()
            if control_type == "ts":
                control_type = "tts"
            control_value = match.group(2).strip()
            if control_type == "tts":
                if controls.tts_emotion_key is not None and controls.tts_emotion_key != control_value:
                    logger.warning(
                        "Duplicate leading tts control tag detected, overriding with latest value: {}", control_value
                    )
                controls.tts_emotion_key = control_value
            else:
                if controls.expression_emotion_key is not None and controls.expression_emotion_key != control_value:
                    logger.warning(
                        "Duplicate leading expression control tag detected, overriding with latest value: {}",
                        control_value,
                    )
                controls.expression_emotion_key = control_value
            index = match.end()
            consumed_any = True

        if not consumed_any:
            return None, text, False

        return controls, text[index:].lstrip(), False

    def _clean_stream_text(self, text: str) -> str:
        cleaned = self.cleaner.clean(text)
        return cleaned.strip()

    def _build_sentences(self, texts: list[str], tags: list[TagInfo] | None = None) -> list[SentenceWithTags]:
        sentence_tags = tags or self._default_tags()
        result: list[SentenceWithTags] = []
        merged_texts, trailing_short = _merge_short_sentence_texts(texts, max_sentence_len=self.max_sentence_len)
        if trailing_short:
            merged_texts.append(trailing_short)
        attach_pending_controls = not self._pending_control_tags.is_empty()
        for text in merged_texts:
            cleaned = self._clean_stream_text(text)
            if cleaned:
                control_tags = self._take_pending_control_tags() if attach_pending_controls else ControlTags()
                attach_pending_controls = False
                result.append(SentenceWithTags(text=cleaned, tags=sentence_tags, control_tags=control_tags))
        return result

    def _flush_plain_buffer(self, *, force: bool = False, final: bool = False) -> list[SentenceWithTags]:
        """刷新纯文本缓冲区，并复用统一分句路径输出结果。

        这是 plain text buffer 的统一出口。普通流式文本会先进入 `_buffer`，
        再在这里决定是否调用 Full 分句路径、是否继续保留尾部残句，以及是否
        达到当前允许输出的稳定句子数量。

        Args:
            force: 是否强制输出当前缓冲中的可用内容。
            final: 是否作为流结束时的最终刷新。

        Returns:
            list[SentenceWithTags]: 当前可以安全输出的句子列表。
        """
        if not self._buffer.strip():
            return []

        if final:
            sentences = segment_full(
                self._buffer,
                cleaner=self.cleaner,
                max_sentence_len=self.max_sentence_len,
                segment_method=self.segment_method,
            )
            self._buffer = ""
            if sentences:
                self._is_first_sentence = False
            return self._build_sentences(sentences)

        sentences, remaining = _segment_document(
            self._buffer,
            max_sentence_len=self.max_sentence_len,
            segment_method=self.segment_method,
            include_incomplete_tail=False,
        )
        sentences, trailing_short = _merge_short_sentence_texts(
            sentences,
            hold_trailing_short=not force,
            max_sentence_len=self.max_sentence_len,
        )
        if trailing_short:
            remaining = f"{trailing_short}{remaining}".strip()

        if not force and len(sentences) < self.stream_min_sentences:
            return []

        if force and remaining.strip():
            sentences = [*sentences, remaining.strip()]
            remaining = ""

        if not sentences:
            return []

        self._buffer = remaining
        self._is_first_sentence = False
        return self._build_sentences(sentences)

    async def _process_buffer(self, *, final: bool = False) -> list[SentenceWithTags]:
        result: list[SentenceWithTags] = []

        while self._buffer.strip():
            if not self._tag_stack:
                controls, remaining, incomplete = self._extract_leading_control_tags(self._buffer)
                if incomplete and not final:
                    break
                if controls is not None and not incomplete:
                    self._merge_pending_control_tags(controls)
                    self._buffer = remaining
                    if not self._buffer.strip():
                        break
                    continue

            next_tag_pos = self._find_next_tag_pos()

            if next_tag_pos == 0:
                tag_info, remaining = self._extract_tag(self._buffer)
                if tag_info:
                    marker_text = self._buffer[: len(self._buffer) - len(remaining)].strip()
                    if marker_text:
                        result.append(SentenceWithTags(text=marker_text, tags=[tag_info]))
                    self._buffer = remaining
                    continue

            elif next_tag_pos < len(self._buffer):
                text_before_tag = self._buffer[:next_tag_pos]
                current_tags = self._get_current_tags()

                if current_tags and text_before_tag.strip():
                    result.extend(self._build_sentences([text_before_tag], current_tags))
                elif text_before_tag.strip():
                    original_buffer = self._buffer
                    self._buffer = text_before_tag
                    result.extend(self._flush_plain_buffer(force=True, final=False))
                    self._buffer = original_buffer[next_tag_pos:]
                else:
                    self._buffer = self._buffer[next_tag_pos:]

                tag_info, remaining = self._extract_tag(self._buffer)
                if tag_info:
                    marker_text = self._buffer[: len(self._buffer) - len(remaining)].strip()
                    if marker_text:
                        result.append(SentenceWithTags(text=marker_text, tags=[tag_info]))
                    self._buffer = remaining
                continue

            current_tags = self._get_current_tags()
            if current_tags:
                if final:
                    result.extend(self._build_sentences([self._buffer], current_tags))
                    self._buffer = ""
                    break

                structural_boundary = _find_structural_boundary(self._buffer)
                if structural_boundary is not None:
                    boundary_start, boundary_end = structural_boundary
                    result.extend(self._build_sentences([self._buffer[:boundary_start]], current_tags))
                    self._buffer = self._buffer[boundary_end:].lstrip()
                    continue

                if contains_end_punctuation(self._buffer):
                    sentences, remaining = self._segment_text(self._buffer)
                    if not sentences:
                        break
                    self._buffer = remaining
                    self._is_first_sentence = False
                    result.extend(self._build_sentences(sentences, current_tags))
                    continue
                break

            structural_boundary = _find_structural_boundary(self._buffer)
            if structural_boundary is not None:
                boundary_start, boundary_end = structural_boundary
                text_before_boundary = self._buffer[:boundary_start]
                original_tail = self._buffer[boundary_end:].lstrip()
                self._buffer = text_before_boundary
                result.extend(self._flush_plain_buffer(force=True, final=False))
                self._buffer = original_tail
                continue

            flushed = self._flush_plain_buffer(force=False, final=final)
            if flushed:
                result.extend(flushed)
                continue
            break

        return result

    @overload
    def process_stream(self, segment_stream: AsyncIterator[str]) -> AsyncIterator[SentenceWithTags]: ...

    @overload
    def process_stream(
        self, segment_stream: AsyncIterator[str | AudioOutput | ToolCallEvent]
    ) -> AsyncIterator[SentenceWithTags | AudioOutput | ToolCallEvent]: ...

    async def process_stream(
        self, segment_stream: AsyncIterator[str | AudioOutput | ToolCallEvent]
    ) -> AsyncIterator[SentenceWithTags | AudioOutput | ToolCallEvent]:
        """处理流式输出，并在内部复用统一的分句与缓冲逻辑。

        该入口主要负责持续积攒 stream 片段、维护 tag 状态，并在检测到
        标点、结构边界或标签时触发内部刷新。真正的清洗、分句和短句合并，
        统一交给 divider 内部的共享路径处理，避免维护两套平行规则。

        Args:
            segment_stream: 上游返回的流式文本、音频输出或 tool call 事件迭代器。

        Yields:
            SentenceWithTags | AudioOutput: 处理后的句子或原样透传的音频输出。
        """
        self._full_response = []
        logger.info("Starting sentence processing stream...")
        async for segment in segment_stream:
            if isinstance(segment, (AudioOutput, ToolCallEvent)):
                yield segment
                continue

            self._buffer += segment
            self._full_response.append(segment)

            should_process = (
                any(re.search(f"{tag}(?:/)?>", self._buffer) for tag in self.valid_tags)
                or has_punctuation(self._buffer)
                or _find_structural_boundary(self._buffer) is not None
            )

            if should_process:
                for sentence in await self._process_buffer(final=False):
                    yield sentence

        if self._buffer.strip():
            for sentence in await self._process_buffer(final=True):
                yield sentence

    @property
    def complete_response(self) -> str:
        return "".join(self._full_response)

    def _segment_text(self, text: str) -> tuple[list[str], str]:
        return _segment_with_method(text, self.segment_method)

    def reset(self):
        self._is_first_sentence = True
        self._buffer = ""
        self._tag_stack = []
        self._pending_control_tags = ControlTags()
        self._full_response = []
