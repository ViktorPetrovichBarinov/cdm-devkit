from __future__ import annotations

from pathlib import Path

from antlr4 import InputStream

from cocas.assembler.ast_builder import build_ast
from cocas.assembler.macro_processor import process_macros, read_mlb
from cocas.assembler.targets import import_target, standard_mlb


def _collect_mnemonics(program_node) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int, int]] = []

    def walk_lines(lines):
        for n in lines:
            # InstructionNode has fields: mnemonic, arguments, location
            if n.__class__.__name__ == "InstructionNode":
                loc = getattr(n, "location", None)
                file = getattr(loc, "file", "") if loc else ""
                line = getattr(loc, "line", 0) if loc else 0
                col = getattr(loc, "column", 0) if loc else 0
                out.append((getattr(n, "mnemonic", ""), file, line, col))
            # Structured statements that nest lines
            elif n.__class__.__name__ == "ConditionalStatementNode":
                for c in getattr(n, "conditions", []):
                    walk_lines(getattr(c, "lines", []))
                walk_lines(getattr(n, "then_lines", []))
                walk_lines(getattr(n, "else_lines", []))
            elif n.__class__.__name__ == "WhileLoopNode":
                walk_lines(getattr(n, "condition_lines", []))
                walk_lines(getattr(n, "lines", []))
            elif n.__class__.__name__ == "UntilLoopNode":
                walk_lines(getattr(n, "lines", []))

    for s in getattr(program_node, "absolute_sections", []):
        walk_lines(getattr(s, "lines", []))
    for s in getattr(program_node, "relocatable_sections", []):
        walk_lines(getattr(s, "lines", []))
    for s in getattr(program_node, "template_sections", []):
        walk_lines(getattr(s, "lines", []))

    return out


def _collect_located_nodes(program_node) -> list[tuple[str, str, int, int]]:
    """
    Collect (node_type, file, line) for nodes that carry a location.

    This is intended for logging/debugging.
    """
    out: list[tuple[str, str, int, int]] = []
    seen: set[int] = set()

    def try_add(obj) -> None:
        loc = getattr(obj, "location", None)
        if not loc:
            return
        file = getattr(loc, "file", "") or ""
        line = getattr(loc, "line", 0) or 0
        col = getattr(loc, "column", 0) or 0
        if file and line:
            out.append((obj.__class__.__name__, str(file), int(line), int(col)))

    def walk(obj) -> None:
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)

        if obj is None:
            return
        if isinstance(obj, (list, tuple)):
            for x in obj:
                walk(x)
            return

        if hasattr(obj, "__dict__"):
            try_add(obj)
            for v in obj.__dict__.values():
                walk(v)

    walk(program_node)
    return out


def ast_file_to_string(filepath: Path, target: str) -> str:
    """
    Build a semantic AST (ProgramNode) from a saved source file and return it as a string.

    This uses the same pipeline as cocas assembler:
    - load standard macros for the given target
    - expand macros
    - parse and build AST
    """
    source = filepath.read_text(encoding="utf-8")
    if not source.endswith("\n"):
        source += "\n"

    target_instructions = import_target(target)
    macros = read_mlb(standard_mlb(target))

    input_stream = InputStream(source)
    expanded_stream = process_macros(input_stream, macros, filepath)
    program_node = build_ast(expanded_stream, filepath)

    mnemonics = _collect_mnemonics(program_node)
    mnemonics_s = "\n".join([f"{m}\t{f}:{l}:{c}" for (m, f, l, c) in mnemonics])

    located_nodes = _collect_located_nodes(program_node)
    located_nodes_s = "\n".join([f"{t}\t{f}:{l}:{c}" for (t, f, l, c) in located_nodes])

    return "\n".join(
        [
            repr(program_node),
            "",
            "MNEMONICS (mnemonic\\tfile:line:column):",
            mnemonics_s,
            "",
            "LOCATED NODES (type\\tfile:line:column):",
            located_nodes_s,
        ]
    )

