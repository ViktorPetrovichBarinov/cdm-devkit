from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path

from lsprotocol import types

from cocas.assembler.macro_processor import read_mlb
from cocas.assembler.targets import list_assembler_targets, standard_mlb

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Keywords / pseudo-ops shared with cocas Asm grammar (and cdm8e extensions).
_GRAMMAR_KEYWORDS: frozenset[str] = frozenset(
    {
        "asect",
        "rsect",
        "tplate",
        "macro",
        "mend",
        "end",
        "if",
        "then",
        "else",
        "fi",
        "while",
        "stays",
        "wend",
        "do",
        "until",
        "break",
        "continue",
        "ext",
        "is",
        "goto",
        "save",
        "restore",
        "low",
        "high",
    }
)

_MAX_ITEMS = 300


def _prefix_span(line: str, character: int) -> tuple[int, int]:
    """Start (inclusive) and end (exclusive) character indices of the identifier prefix before cursor."""
    col = min(max(0, character), len(line))
    i = col - 1
    while i >= 0 and (line[i].isalnum() or line[i] in "_"):
        i -= 1
    start = i + 1
    return start, col


def _target_instruction_names(target: str) -> set[str]:
    out: set[str] = set()
    try:
        mod = importlib.import_module(f"cocas.assembler.targets.{target}.target_instructions")
    except Exception:
        return out

    ci = getattr(mod, "cpu_instructions", None)
    if isinstance(ci, dict):
        out |= set(ci.keys())

    si = getattr(mod, "special_instructions", None)
    if isinstance(si, dict):
        out |= set(si.keys())

    ad = getattr(mod, "assembler_directives", None)
    if isinstance(ad, dict):
        out |= set(ad.keys())

    for h in getattr(mod, "handlers", None) or []:
        instr = getattr(h, "instructions", None)
        if isinstance(instr, dict):
            out |= set(instr.keys())

    asm_dirs = getattr(mod, "assembly_directives", None)
    if callable(asm_dirs):
        try:
            d = asm_dirs()
            if isinstance(d, (set, frozenset)):
                out |= set(d)
            elif isinstance(d, (list, tuple)):
                out |= set(d)
        except Exception:
            pass

    return out


def _standard_macro_names(target: str) -> set[str]:
    try:
        if target not in list_assembler_targets():
            return set()
        return set(read_mlb(standard_mlb(target)).keys())
    except Exception:
        return set()


def _hover_json_keys(target: str) -> set[str]:
    p = _DATA_DIR / f"{target}_mnemonics.json"
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return set((data.get("mnemonics") or {}).keys())
    except Exception:
        return set()


def _hover_json_mtime(target: str) -> float:
    p = _DATA_DIR / f"{target}_mnemonics.json"
    try:
        return p.stat().st_mtime if p.is_file() else 0.0
    except OSError:
        return 0.0


@lru_cache(maxsize=64)
def _all_candidates_frozen(dialect: str, _hover_mtime: float) -> frozenset[str]:
    s = set(_GRAMMAR_KEYWORDS)
    s |= _target_instruction_names(dialect)
    s |= _standard_macro_names(dialect)
    s |= _hover_json_keys(dialect)
    return frozenset(s)


def completion_list(
    *,
    line_text: str,
    line: int,
    character: int,
    dialect: str,
) -> types.CompletionList:
    start, end = _prefix_span(line_text, character)
    prefix = line_text[start:end]
    prefix_l = prefix.lower()

    candidates = sorted(_all_candidates_frozen(dialect, _hover_json_mtime(dialect)))
    if prefix_l:
        matches = [c for c in candidates if c.lower().startswith(prefix_l)]
    else:
        matches = candidates

    matches = matches[:_MAX_ITEMS]
    edit_range = types.Range(
        start=types.Position(line=line, character=start),
        end=types.Position(line=line, character=end),
    )

    items: list[types.CompletionItem] = []
    for m in matches:
        kind = (
            types.CompletionItemKind.Keyword
            if m in _GRAMMAR_KEYWORDS
            else types.CompletionItemKind.Function
        )
        items.append(
            types.CompletionItem(
                label=m,
                kind=kind,
                filter_text=m,
                text_edit=types.TextEdit(range=edit_range, new_text=m),
            )
        )

    return types.CompletionList(
        is_incomplete=len(matches) >= _MAX_ITEMS,
        items=items,
    )
