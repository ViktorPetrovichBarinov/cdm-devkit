from __future__ import annotations

from pathlib import Path

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener
from lsprotocol import types
from pygls import uris

from cocas.assembler import list_assembler_targets
from cocas.assembler.generated import MacroLexer, MacroParser
from cocas.assembler.macro_processor import ExpandMacrosVisitor, MacroDefinition, read_mlb
from cocas.assembler.targets import standard_mlb
from cocas.object_module import CodeLocation


class _SilentErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        return


def read_mlb_from_source(source: str, filepath: Path) -> dict[str, dict[int, MacroDefinition]]:
    """Parse `.mlb` buffer like `read_mlb` on disk (locations use `filepath`)."""
    str_path = filepath.absolute().as_posix()
    data = source if source.endswith("\n") else source + "\n"
    lexer = MacroLexer(InputStream(data))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())
    token_stream = CommonTokenStream(lexer)
    parser = MacroParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())
    cst = parser.mlb()
    emv = ExpandMacrosVisitor(None, dict(), str_path)
    return emv.visit(cst)


def collect_macros_asm_from_source(source: str, filepath: Path) -> dict[str, dict[int, MacroDefinition]]:
    """Macro definitions in an `.asm` buffer (`macro` … `mend`); bodies omitted (only `location` is used)."""
    str_path = filepath.absolute().as_posix()
    src = source if source.endswith("\n") else source + "\n"
    lexer = MacroLexer(InputStream(src))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())
    parser = MacroParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())
    tree = parser.program()
    out: dict[str, dict[int, MacroDefinition]] = {}

    def walk(node) -> None:
        if node.__class__.__name__ == "MacroContext":
            hdr = node.macro_header()
            name = hdr.NAME().getText()
            arity = int(hdr.DIGIT().getText())
            line = node.macro_body().start.line
            m = MacroDefinition(name, arity, [], CodeLocation(str_path, line, 0))
            out.setdefault(name, {})[arity] = m
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(tree)
    return out


def _paths_resolved_equal(a: str | Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except OSError:
        return False


def _range_for_line(lines: list[str], line0: int) -> types.Range:
    if line0 < 0 or line0 >= len(lines):
        return types.Range(
            start=types.Position(line=max(0, line0), character=0),
            end=types.Position(line=max(0, line0), character=1),
        )
    text = lines[line0]
    span = len(text.rstrip("\r\n"))
    if span < 1:
        span = 1
    return types.Range(
        start=types.Position(line=line0, character=0),
        end=types.Position(line=line0, character=span),
    )


def _locations_from_arity_map(
    per_arity: dict[int, MacroDefinition],
    *,
    doc_lines: list[str],
    doc_path: Path,
) -> list[types.Location]:
    out: list[types.Location] = []
    for _arity, m in sorted(per_arity.items(), key=lambda x: x[0]):
        loc = m.location
        if not loc.file:
            continue
        path = Path(loc.file)
        line0 = max(0, loc.line - 1)
        if _paths_resolved_equal(path, doc_path):
            r = _range_for_line(doc_lines, line0)
        else:
            try:
                disk_lines = path.read_text(encoding="utf-8").splitlines()
                r = _range_for_line(disk_lines, line0)
            except OSError:
                r = types.Range(
                    start=types.Position(line=line0, character=0),
                    end=types.Position(line=line0, character=1),
                )
        uri = uris.from_fs_path(path.as_posix())
        if uri:
            out.append(types.Location(uri=uri, range=r))
    return out


def macro_definition_locations(
    word: str | None,
    *,
    source: str,
    file_path: Path,
    doc_lines: list[str],
    dialect: str,
) -> list[types.Location] | None:
    """
    Go to definition for a macro: current buffer first, then `standard_mlb(dialect)`.
    """
    if not word:
        return None

    local: dict[str, dict[int, MacroDefinition]] = {}
    try:
        suf = file_path.suffix.lower()
        if suf == ".mlb":
            local = read_mlb_from_source(source, file_path)
        elif suf == ".asm":
            local = collect_macros_asm_from_source(source, file_path)
    except Exception:
        local = {}

    if word in local:
        return _locations_from_arity_map(local[word], doc_lines=doc_lines, doc_path=file_path)

    if dialect not in list_assembler_targets():
        return None

    try:
        std_path = standard_mlb(dialect)
        std = read_mlb(std_path)
    except Exception:
        return None

    if word not in std:
        return None

    try:
        std_lines = std_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        std_lines = []

    return _locations_from_arity_map(std[word], doc_lines=std_lines, doc_path=std_path)
