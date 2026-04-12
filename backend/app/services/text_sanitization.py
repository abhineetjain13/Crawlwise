from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
)

_MAX_UI_NOISE_REGEX_INPUT_CHARS = 12000
_UI_NOISE_TOKEN_RE = (
    re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_NOISE_TOKEN_PATTERN
    else None
)
_UI_ICON_TOKEN_RE = (
    re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_ICON_TOKEN_PATTERN
    else None
)
_SCRIPT_NOISE_RE = (
    re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE)
    if CANDIDATE_SCRIPT_NOISE_PATTERN
    else None
)
_NON_EMPTY_UI_NOISE_PHRASES = [phrase for phrase in CANDIDATE_UI_NOISE_PHRASES if phrase]
_UI_NOISE_PHRASES_RE = (
    re.compile(
        r"\b(?:" + "|".join(re.escape(phrase) for phrase in _NON_EMPTY_UI_NOISE_PHRASES) + r")\b",
        re.IGNORECASE,
    )
    if _NON_EMPTY_UI_NOISE_PHRASES
    else None
)


def _bounded_noise_text(value: object) -> str:
    text = str(value or "")
    if len(text) <= _MAX_UI_NOISE_REGEX_INPUT_CHARS:
        return text
    return text[:_MAX_UI_NOISE_REGEX_INPUT_CHARS]


def strip_ui_noise(value: object, *, preserve_newlines: bool = False) -> str:
    text = _bounded_noise_text(value)
    if not text:
        return ""
    if _UI_ICON_TOKEN_RE:
        text = _UI_ICON_TOKEN_RE.sub(" ", text)
    if _UI_NOISE_TOKEN_RE:
        text = _UI_NOISE_TOKEN_RE.sub(" ", text)
    if _SCRIPT_NOISE_RE:
        text = _SCRIPT_NOISE_RE.sub(" ", text)
    if _UI_NOISE_PHRASES_RE:
        text = _UI_NOISE_PHRASES_RE.sub(" ", text)
    if preserve_newlines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.strip(" -|,:;/") for line in text.split("\n"))
        return text.strip()
    return re.sub(r"\s+", " ", text).strip(" -|,:;/")
