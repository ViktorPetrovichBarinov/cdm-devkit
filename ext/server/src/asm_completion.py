from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def _target_instruction_buckets(target: str) -> tuple[set[str], set[str], set[str]]:
    """Return (instructions, directives, specials) names from target module."""
    instructions: set[str] = set()
    directives: set[str] = set()
    specials: set[str] = set()
    try:
        mod = importlib.import_module(f"cocas.assembler.targets.{target}.target_instructions")
    except Exception:
        return instructions, directives, specials

    ci = getattr(mod, "cpu_instructions", None)
    if isinstance(ci, dict):
        instructions |= set(ci.keys())

    si = getattr(mod, "special_instructions", None)
    if isinstance(si, dict):
        specials |= set(si.keys())

    ad = getattr(mod, "assembler_directives", None)
    if isinstance(ad, dict):
        directives |= set(ad.keys())

    for h in getattr(mod, "handlers", None) or []:
        instr = getattr(h, "instructions", None)
        if isinstance(instr, dict):
            instructions |= set(instr.keys())

    asm_dirs = getattr(mod, "assembly_directives", None)
    if callable(asm_dirs):
        try:
            d = asm_dirs()
            if isinstance(d, (set, frozenset)):
                directives |= set(d)
            elif isinstance(d, (list, tuple)):
                directives |= set(d)
        except Exception:
            pass
    return instructions, directives, specials


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


def _hover_json_table(target: str) -> dict[str, Any]:
    p = _DATA_DIR / f"{target}_mnemonics.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    table = data.get("mnemonics") or {}
    return table if isinstance(table, dict) else {}


def _description_entry_from_json(dialect: str, symbol: str) -> dict[str, Any]:
    """
    Return symbol metadata from JSON only.
    Tries active dialect first, then cdm8e (most populated dataset).
    """
    key = symbol.lower()
    dialects = [dialect] + ([] if dialect == "cdm8e" else ["cdm8e"])
    for d in dialects:
        entry = _hover_json_table(d).get(key)
        if isinstance(entry, dict):
            return entry
    return {}


@lru_cache(maxsize=64)
def _all_candidates_frozen(dialect: str, _hover_mtime: float) -> frozenset[str]:
    s = set(_GRAMMAR_KEYWORDS)
    s |= _target_instruction_names(dialect)
    s |= _standard_macro_names(dialect)
    s |= _hover_json_keys(dialect)
    return frozenset(s)


@lru_cache(maxsize=64)
def _candidate_meta_frozen(dialect: str, _hover_mtime: float) -> dict[str, dict[str, str]]:
    """
    Metadata for completion UI:
    - category: keyword | macro | instruction | directive | special
    - description: short human-readable hint
    """
    meta: dict[str, dict[str, str]] = {}

    for kw in _GRAMMAR_KEYWORDS:
        meta[kw] = {"category": "keyword", "description": "Assembler keyword/directive"}

    for m in _standard_macro_names(dialect):
        meta[m] = {"category": "macro", "description": "Standard macro"}

    instructions, directives, specials = _target_instruction_buckets(dialect)
    for n in instructions:
        meta.setdefault(n, {"category": "instruction", "description": "CPU instruction"})
    for n in directives:
        meta.setdefault(n, {"category": "directive", "description": "Assembler directive"})
    for n in specials:
        meta.setdefault(n, {"category": "special", "description": "Special instruction"})

    merged_table: dict[str, Any] = {}
    # Active dialect overrides cdm8e fallback.
    merged_table.update(_hover_json_table("cdm8e"))
    if dialect != "cdm8e":
        merged_table.update(_hover_json_table(dialect))
    for name, entry in merged_table.items():
        if not isinstance(entry, dict):
            continue
        desc = str(entry.get("description") or "").strip()
        syntax = str(entry.get("syntax") or "").strip()
        cat = str(entry.get("category") or "").strip().lower()
        current = meta.setdefault(name, {"category": "instruction", "description": "Instruction"})
        if cat:
            current["category"] = cat
        if desc:
            current["description"] = desc
        if syntax:
            current["syntax"] = syntax
    return meta


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
    meta = _candidate_meta_frozen(dialect, _hover_json_mtime(dialect))
    for m in matches:
        m_meta = meta.get(m) or meta.get(m.lower()) or {}
        json_entry = _description_entry_from_json(dialect, m)
        category = str(json_entry.get("category") or m_meta.get("category") or "symbol")
        description = str(json_entry.get("description") or "").strip()
        syntax = str(json_entry.get("syntax") or "").strip()
        short_desc = description.replace("\n", " ").strip()
        if short_desc and len(short_desc) > 96:
            short_desc = short_desc[:93].rstrip() + "..."
        detail = f"{category} - {short_desc}" if short_desc else category

        doc_lines = [f"**{m}**"]
        if short_desc:
            doc_lines.extend(["", short_desc])
        if syntax:
            doc_lines.extend(["", f"Syntax: `{syntax}`"])

        kind = (
            types.CompletionItemKind.Keyword
            if m in _GRAMMAR_KEYWORDS
            else types.CompletionItemKind.Function
        )
        items.append(
            types.CompletionItem(
                label=m,
                kind=kind,
                detail=detail,
                label_details=types.CompletionItemLabelDetails(
                    description=short_desc or None,
                ),
                documentation=types.MarkupContent(
                    kind=types.MarkupKind.Markdown,
                    value="\n".join(doc_lines),
                ),
                filter_text=m,
                text_edit=types.TextEdit(range=edit_range, new_text=m),
            )
        )

    return types.CompletionList(
        is_incomplete=len(matches) >= _MAX_ITEMS,
        items=items,
    )
