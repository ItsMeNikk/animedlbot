from __future__ import annotations

import re
import html
from typing import Optional

_STOPWORDS = {
    "search",
    "find",
    "please",
    "pls",
    "download",
}

_BR_RE = re.compile(r"<\s*br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")


def normalize_query(raw: str) -> str:
    if not raw:
        return raw
    # remove leading/trailing whitespace and quotes
    text = raw.strip().strip('"\'')
    # remove Telegram mentions and extra punctuation edges
    text = re.sub(r"@[\w_]+", "", text)
    # collapse whitespace
    parts = [w for w in re.split(r"\s+", text) if w]
    # drop simple stopwords (case-insensitive)
    filtered = [w for w in parts if w.lower() not in _STOPWORDS]
    if not filtered:
        filtered = parts
    return " ".join(filtered)


def escape_html(text: Optional[str]) -> str:
    if not text:
        return ""
    return html.escape(text, quote=False)


def sanitize_description(text: Optional[str], max_len: int = 900) -> str:
    if not text:
        return ""
    # Replace <br> with newlines and strip remaining tags if any leaked in
    cleaned = _BR_RE.sub("\n", text)
    cleaned = _TAG_RE.sub("", cleaned)
    # Normalize whitespace and collapse multiple blank lines
    cleaned = cleaned.replace("\r", "")
    # Collapse horizontal whitespace
    cleaned = _WS_RE.sub(" ", cleaned)
    # Trim lines and collapse multiple newlines
    lines = [line.strip() for line in cleaned.split("\n")]
    cleaned = "\n".join([ln for ln in lines if ln])
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


