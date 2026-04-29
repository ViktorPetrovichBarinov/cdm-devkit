from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from lsprotocol import types

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# One JSON per dialect (editable source of truth under server/data/).
_HOVER_JSON_BY_DIALECT: dict[str, str] = {
    "cdm8": "cdm8_mnemonics.json",
    "cdm8e": "cdm8e_mnemonics.json",
    "cdm16": "cdm16_mnemonics.json",
    "cdm16e": "cdm16e_mnemonics.json",
}

# path key -> (mtime, mnemonics dict)
_mnemonics_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _hover_json_path(dialect: str) -> Optional[Path]:
    name = _HOVER_JSON_BY_DIALECT.get(dialect)
    if not name:
        return None
    p = _DATA_DIR / name
    return p if p.is_file() else None


def _load_mnemonics(dialect: str) -> dict[str, Any]:
    """Load mnemonics for dialect; reload when the backing JSON mtime changes."""
    path = _hover_json_path(dialect)
    if path is None:
        return {}
    key = str(path.resolve())
    mtime = path.stat().st_mtime
    hit = _mnemonics_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    table = data.get("mnemonics") or {}
    _mnemonics_cache[key] = (mtime, table)
    return table


def word_at_cursor(line: str, character: int) -> Optional[str]:
    """Return alphanumeric/underscore word under or adjacent to `character` (0-based UTF-16-ish offset)."""
    if not line:
        return None
    col = max(0, min(character, len(line)))
    idx = col
    if idx >= len(line):
        idx = len(line) - 1
    if idx < 0:
        return None

    def is_word_ch(ch: str) -> bool:
        return ch.isalnum() or ch == "_" or ch == "."

    if not is_word_ch(line[idx]):
        if idx > 0 and is_word_ch(line[idx - 1]):
            idx -= 1
        else:
            return None

    start = idx
    while start > 0 and is_word_ch(line[start - 1]):
        start -= 1
    end = idx + 1
    while end < len(line) and is_word_ch(line[end]):
        end += 1
    w = line[start:end].strip()
    if not w:
        return None
    w = re.sub(r"[^a-zA-Z0-9_.]+$", "", w)
    return w or None


def build_hover_markdown(entry: dict, mnemonic: str) -> str:
    desc = entry.get("description") or ""
    syntax = entry.get("syntax") or ""
    example = entry.get("example") or ""
    cat = entry.get("category") or ""
    lines = [f"### `{mnemonic}`"]
    if cat:
        lines.append(f"*({cat})*")
    lines.append("")
    lines.append(desc.strip())
    lines.append("")
    if syntax:
        lines.append(f"**Syntax:** `{syntax}`")
    if example:
        lines.append(f"**Example:** `{example}`")
    return "\n".join(lines).strip()


def hover_for_word(word: str, *, dialect: str) -> Optional[types.Hover]:
    key = word.lower()
    table = _load_mnemonics(dialect)
    entry = table.get(key)
    if not entry:
        return None

    md = build_hover_markdown(entry, key)
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=md),
        range=None,
    )
