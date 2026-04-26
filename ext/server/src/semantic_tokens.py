from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from antlr4 import InputStream
from lsprotocol import types

from cocas.assembler.generated import AsmLexer


# Use standard semantic token types so themes color them naturally.
TOKEN_TYPES = [
    "comment",   # line comments
    "keyword",   # directives + control keywords
    "macro",     # macro definitions/calls
    "type",      # labels (use broadly-supported type for compatibility)
    "function",  # CPU instructions
    "parameter", # registers
    "number",
    "string",
]

KEYWORD_TOKEN_NAMES = {
    "Asect",
    "Break",
    "Continue",
    "Do",
    "Else",
    "End",
    "Ext",
    "Fi",
    "If",
    "Is",
    "Macro",
    "Rsect",
    "Stays",
    "Then",
    "Tplate",
    "Until",
    "Wend",
    "While",
}

NAME_TOKEN_NAMES = KEYWORD_TOKEN_NAMES | {"WORD", "WORD_WITH_DOTS"}


@dataclass(frozen=True)
class _Tok:
    line: int
    col: int
    text: str
    type_name: str


@dataclass(frozen=True)
class _Semantic:
    line: int
    col: int
    length: int
    token_type: str


def legend() -> types.SemanticTokensLegend:
    return types.SemanticTokensLegend(token_types=TOKEN_TYPES, token_modifiers=[])


@lru_cache(maxsize=32)
def _dialect_sets(dialect: str) -> tuple[set[str], set[str], set[str]]:
    """
    Returns (macros, directives, instructions) for a dialect from cocas internals.
    """
    macros: set[str] = set()
    directives: set[str] = set()
    instructions: set[str] = set()
    target_name = (dialect or "cdm8").lower()

    try:
        from cocas.assembler.macro_processor import read_mlb
        from cocas.assembler.targets import import_target, standard_mlb

        target = import_target(target_name)
        directives = set(target.assembly_directives())

        macro_map = read_mlb(standard_mlb(target_name))
        macros = set(macro_map.keys())

        # Collect instruction mnemonics from target handlers.
        module = __import__(
            f"cocas.assembler.targets.{target_name}.target_instructions",
            fromlist=["handlers"],
        )
        for h in getattr(module, "handlers", []):
            instr_map = getattr(h, "instructions", None)
            if isinstance(instr_map, dict):
                instructions.update(instr_map.keys())
    except Exception:
        # Keep empty fallback sets to avoid crashing semantic tokens.
        pass

    instructions.difference_update(directives)
    return macros, directives, instructions


def _antlr_tokens(text: str) -> list[_Tok]:
    lexer = AsmLexer(InputStream(text))
    out: list[_Tok] = []
    for t in lexer.getAllTokens():
        token_type_name = AsmLexer.symbolicNames[t.type]
        out.append(_Tok(line=t.line - 1, col=t.column, text=t.text or "", type_name=token_type_name))
    return out


def _split_by_line(tokens: list[_Tok]) -> dict[int, list[_Tok]]:
    m: dict[int, list[_Tok]] = {}
    for t in tokens:
        m.setdefault(t.line, []).append(t)
    for line in m:
        m[line].sort(key=lambda x: x.col)
    return m


def _find_mnemonic_index(line_tokens: list[_Tok]) -> int | None:
    """
    Find index of line mnemonic token according to grammar shape:
    labels_declaration? instruction arguments?
    where instruction is WORD.
    """
    if not line_tokens:
        return None

    i = 0
    # Optional labels_declaration at line start:
    # labels (COMMA labels)* (COLON | ANGLE_BRACKET)
    start = i
    if i < len(line_tokens) and line_tokens[i].type_name in NAME_TOKEN_NAMES:
        i += 1
        while i + 1 < len(line_tokens) and line_tokens[i].type_name == "COMMA" and line_tokens[i + 1].type_name in NAME_TOKEN_NAMES:
            i += 2
        if i < len(line_tokens) and line_tokens[i].type_name in {"COLON", "ANGLE_BRACKET"}:
            i += 1
        else:
            i = start

    # First WORD after optional label-declaration is mnemonic.
    if i < len(line_tokens) and line_tokens[i].type_name == "WORD":
        return i
    return None


def _label_declaration_indices(line_tokens: list[_Tok]) -> list[int]:
    """
    Returns token indices for labels in leading labels_declaration:
    labels (COMMA labels)* (COLON | ANGLE_BRACKET)
    """
    if not line_tokens:
        return []

    indices: list[int] = []
    i = 0

    if i >= len(line_tokens) or line_tokens[i].type_name not in NAME_TOKEN_NAMES:
        return []

    indices.append(i)
    i += 1

    while i + 1 < len(line_tokens) and line_tokens[i].type_name == "COMMA" and line_tokens[i + 1].type_name in NAME_TOKEN_NAMES:
        indices.append(i + 1)
        i += 2

    if i < len(line_tokens) and line_tokens[i].type_name in {"COLON", "ANGLE_BRACKET"}:
        return indices

    return []


def _semantic_for_token(t: _Tok) -> str | None:
    if t.type_name in KEYWORD_TOKEN_NAMES:
        return "keyword"
    if t.type_name == "REGISTER":
        return "parameter"
    if t.type_name in {"DECIMAL_NUMBER", "HEX_NUMBER", "BINARY_NUMBER"}:
        return "number"
    if t.type_name in {"STRING", "CHAR"}:
        return "string"
    if t.type_name == "WORD_WITH_DOTS":
        return "type"
    return None


def _line_comment_tokens(text: str) -> list[_Semantic]:
    out: list[_Semantic] = []
    for i, line in enumerate(text.splitlines()):
        idx = line.find("#")
        if idx >= 0:
            out.append(_Semantic(i, idx, len(line) - idx, "comment"))
    return out


def tokenize_semantic(text: str, dialect: str) -> list[_Semantic]:
    macros, directives, instructions = _dialect_sets(dialect)
    toks = _antlr_tokens(text)
    by_line = _split_by_line(toks)

    semantic: list[_Semantic] = []

    # Comments are skipped by lexer grammar, so add them manually.
    semantic.extend(_line_comment_tokens(text))

    for line, line_tokens in by_line.items():
        mnemonic_idx = _find_mnemonic_index(line_tokens)
        label_indices = set(_label_declaration_indices(line_tokens))

        for idx, t in enumerate(line_tokens):
            if idx in label_indices:
                semantic.append(_Semantic(line, t.col, len(t.text), "type"))

            typ = _semantic_for_token(t)
            if typ is not None:
                semantic.append(_Semantic(line, t.col, len(t.text), typ))

            if mnemonic_idx is not None and idx == mnemonic_idx:
                mn = t.text
                if mn in macros:
                    semantic.append(_Semantic(line, t.col, len(mn), "macro"))
                elif mn in directives:
                    semantic.append(_Semantic(line, t.col, len(mn), "keyword"))
                elif mn in instructions or mn.startswith("b"):
                    semantic.append(_Semantic(line, t.col, len(mn), "function"))

            # Label references in instruction arguments (e.g. `jsr func`, `ldi r0, computed_func`)
            # are plain WORD/WORD_WITH_DOTS tokens after mnemonic position.
            if (
                mnemonic_idx is not None
                and idx > mnemonic_idx
                and t.type_name in {"WORD", "WORD_WITH_DOTS"}
            ):
                semantic.append(_Semantic(line, t.col, len(t.text), "type"))

        # Macro definition token: *name/arity (first WORD after ASTERISK at line start).
        if (
            len(line_tokens) >= 3
            and line_tokens[0].type_name == "ASTERISK"
            and line_tokens[1].type_name == "WORD"
        ):
            semantic.append(
                _Semantic(line, line_tokens[1].col, len(line_tokens[1].text), "macro")
            )

    semantic.sort(key=lambda x: (x.line, x.col, x.length, x.token_type))
    return semantic


def encode(tokens: Iterable[_Semantic]) -> list[int]:
    type_idx = {name: i for i, name in enumerate(TOKEN_TYPES)}
    data: list[int] = []
    prev_line = 0
    prev_col = 0
    first = True

    for t in tokens:
        idx = type_idx.get(t.token_type)
        if idx is None or t.length <= 0:
            continue
        if first:
            delta_line = t.line
            delta_col = t.col
            first = False
        else:
            delta_line = t.line - prev_line
            delta_col = t.col - (prev_col if delta_line == 0 else 0)

        data.extend([delta_line, delta_col, t.length, idx, 0])
        prev_line = t.line
        prev_col = t.col

    return data


def semantic_tokens_full(text: str, dialect: str) -> types.SemanticTokens:
    return types.SemanticTokens(data=encode(tokenize_semantic(text, dialect)))

