import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import antlr4
from antlr4 import CommonTokenStream, InputStream

from cocas.assembler.ast_builder import BuildAstVisitor
from cocas.assembler.exceptions import AntlrErrorListener, AssemblerException, AssemblerExceptionTag
from cocas.assembler.generated import AsmLexer, AsmParser
from cocas.assembler.macro_processor import process_macros, read_mlb
from cocas.assembler.targets import import_target, standard_mlb
from cocas.object_module import CodeLocation


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return Path(unquote(uri))


class _BuildAstVisitorWithColumns(BuildAstVisitor):
    def _ctx_location(self, ctx) -> CodeLocation:
        if self.in_macro:
            # Macro-expanded code doesn't carry reliable column information.
            return CodeLocation(self.current_macro_file, self.current_macro_line, 0)
        return CodeLocation(self.source_path, ctx.start.line - self.line_offset, ctx.start.column)


def _build_ast_with_columns(input_stream: InputStream, filepath: Path):
    str_path = filepath.absolute().as_posix()
    lexer = AsmLexer(input_stream)
    lexer.removeErrorListeners()
    lexer.addErrorListener(AntlrErrorListener(AssemblerExceptionTag.ASM, str_path))
    token_stream = CommonTokenStream(lexer)
    token_stream.fill()
    parser = AsmParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(AntlrErrorListener(AssemblerExceptionTag.ASM, str_path))
    cst = parser.program()
    bav = _BuildAstVisitorWithColumns(str_path)
    result = bav.visit(cst)
    return result


def build_program_ast_from_text(source: str, *, uri: str, dialect: str) -> Any:
    """
    Build and return cocas ProgramNode from in-memory document text.

    Raises AssemblerException on syntax/macro/semantic errors.
    """
    file_path = uri_to_path(uri)
    if not source.endswith("\n"):
        source += "\n"

    target_instructions = import_target(dialect)
    macros = read_mlb(standard_mlb(dialect))

    input_stream = antlr4.InputStream(source)
    macro_expanded_input_stream = process_macros(input_stream, macros, file_path)
    program = _build_ast_with_columns(macro_expanded_input_stream, file_path)

    # Force semantic validation (labels/templates/varying length, etc.)
    # Many useful diagnostics come from this stage.
    from cocas.assembler.object_generator import generate_object_module  # local import to keep API surface small

    generate_object_module(program, target_instructions)
    return program


def _json_default(obj: Any):
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, CodeLocation):
        return {"file": obj.file, "line": obj.line, "column": getattr(obj, "column", 0)}
    if is_dataclass(obj):
        # cocas attaches some attributes (e.g. `location`) dynamically, i.e. not as dataclass fields.
        # `asdict()` would drop those, so we merge dataclass fields + extra attributes.
        result: dict[str, Any] = {}
        for f in fields(obj):
            result[f.name] = getattr(obj, f.name)
        extra = getattr(obj, "__dict__", {})
        for k, v in extra.items():
            if k not in result:
                result[k] = v
        return result
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def format_ast_for_log(program: Any, *, max_chars: int = 20000) -> str:
    """
    Human-readable structural dump of AST that preserves node *types* (class names).
    This makes it much easier to understand the real tree shape than JSON alone.
    """

    def loc_str(loc: Any) -> str:
        if isinstance(loc, CodeLocation):
            return f"{loc.file}:{loc.line}:{getattr(loc, 'column', 0)}"
        return str(loc)

    def fmt(obj: Any, indent: str) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, (str, int, float, bool)):
            return repr(obj) if isinstance(obj, str) else str(obj)
        if isinstance(obj, bytes):
            return repr(obj.decode("utf-8", errors="replace"))
        if isinstance(obj, Path):
            return repr(obj.as_posix())
        if isinstance(obj, CodeLocation):
            return f"CodeLocation({loc_str(obj)})"

        if isinstance(obj, list):
            if not obj:
                return "[]"
            items = "\n".join(f"{indent}- {fmt(i, indent + '  ')}" for i in obj)
            return f"[\n{items}\n{indent[:-2]}]"

        if isinstance(obj, dict):
            if not obj:
                return "{}"
            items = "\n".join(f"{indent}{k}: {fmt(v, indent + '  ')}" for k, v in obj.items())
            return f"{{\n{items}\n{indent[:-2]}}}"

        # dataclass nodes (cocas AST nodes)
        if is_dataclass(obj):
            cls = type(obj).__name__
            parts: list[str] = [f"{cls}("]

            # dataclass fields
            for f in fields(obj):
                v = getattr(obj, f.name)
                parts.append(f"{indent}{f.name}={fmt(v, indent + '  ')},")

            # dynamically attached attributes (e.g. `location`)
            extra = getattr(obj, "__dict__", {})
            for k, v in extra.items():
                if k in {f.name for f in fields(obj)}:
                    continue
                parts.append(f"{indent}{k}={fmt(v, indent + '  ')},")

            parts.append(f"{indent[:-2]})")
            return "\n".join(parts)

        # fallback
        if hasattr(obj, "__dict__"):
            return fmt(obj.__dict__, indent)
        return repr(obj)

    text = fmt(program, "  ")
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n... <truncated>\n"
    return text


def try_build_and_format_ast(
    source: str,
    *,
    uri: str,
    dialect: str,
    max_chars: int = 20000,
) -> tuple[Optional[str], Optional[AssemblerException]]:
    try:
        program = build_program_ast_from_text(source, uri=uri, dialect=dialect)
        return format_ast_for_log(program, max_chars=max_chars), None
    except AssemblerException as e:
        return None, e

