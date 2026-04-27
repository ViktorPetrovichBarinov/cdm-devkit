from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from lsprotocol import types

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cdm8e_mnemonics.json"

_cdm8e_cache_mtime: float | None = None
_cdm8e_cache_table: dict[str, Any] = {}


def _load_cdm8e() -> dict[str, Any]:
    """
    Load hover dictionary from server/data/cdm8e_mnemonics.json (single editable source).
    Reloads when the file changes on disk (mtime).
    """
    global _cdm8e_cache_mtime, _cdm8e_cache_table
    if not _DATA_PATH.is_file():
        return {}
    mtime = _DATA_PATH.stat().st_mtime
    if _cdm8e_cache_mtime == mtime:
        return _cdm8e_cache_table
    data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    _cdm8e_cache_table = data.get("mnemonics") or {}
    _cdm8e_cache_mtime = mtime
    return _cdm8e_cache_table


def word_at_cursor(line: str, character: int) -> Optional[str]:
    """Return alphanumeric/underscore word under or adjacent to `character` (0-based UTF-16-ish offset)."""
    if not line:
        return None
    col = max(0, min(character, len(line)))
    # If cursor on delimiter, scan left to word end
    idx = col
    if idx >= len(line):
        idx = len(line) - 1
    if idx < 0:
        return None

    def is_word_ch(ch: str) -> bool:
        return ch.isalnum() or ch == "_" or ch == "."

    if not is_word_ch(line[idx]):
        # try immediate left (VS Code often places cursor after token)
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
    # Strip trailing punctuation sometimes glued (e.g. "halt.")
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
    if dialect != "cdm8e":
        return None
    key = word.lower()
    # Strip leading b for branch? No — mnemonics stored as bz, beq, etc.

    table = _load_cdm8e()
    entry = table.get(key)
    if not entry:
        return None

    md = build_hover_markdown(entry, key)
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=md),
        range=None,
    )
