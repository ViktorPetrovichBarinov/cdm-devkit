from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lsprotocol import types

from cocas.assembler import AssemblerException, assemble_files, list_assembler_targets

if TYPE_CHECKING:
    from pygls.workspace import TextDocument


def _norm_path(p: str | Path) -> Path:
    try:
        return Path(p).expanduser().resolve()
    except OSError:
        return Path(p)


def _paths_same(a: str | Path, b: Path) -> bool:
    try:
        return _norm_path(a) == b.resolve()
    except Exception:
        return str(a) == str(b)


def assembler_exception_to_diagnostic(
    exc: AssemblerException,
    *,
    document_path: Path,
    doc: "TextDocument",
) -> types.Diagnostic:
    """Map AssemblerException to a single LSP diagnostic (whole line if no column in exception)."""
    msg = f"[{exc.tag.value}] {exc.description}"
    line0 = max(0, int(exc.line) - 1)  # cocas uses 1-based lines
    lines = doc.lines
    if line0 >= len(lines):
        line0 = max(0, len(lines) - 1)

    line_text = lines[line0] if lines else ""
    # Strip only trailing newline for span length
    span = len(line_text.rstrip("\r\n"))
    if span <= 0:
        span = 1

    # If error points at another file, still show on this document at top with full path
    if not _paths_same(exc.file, document_path):
        line0 = 0
        span = min(len(lines[0].rstrip("\r\n")) if lines else 1, 80) or 1
        msg = f"{msg}\n(location: {exc.file}:{exc.line})"

    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=line0, character=0),
            end=types.Position(line=line0, character=span),
        ),
        message=msg,
        severity=types.DiagnosticSeverity.Error,
        source="cocas",
    )


def build_assemble_diagnostics(file_path: Path, doc: "TextDocument", dialect: str) -> list[types.Diagnostic]:
    """
    Run cocas assemble_files on one saved .asm file; return LSP diagnostics (empty if OK).
    """
    if dialect not in list_assembler_targets():
        return [
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=0, character=1),
                ),
                message=f"Unknown assembler target '{dialect}'.",
                severity=types.DiagnosticSeverity.Error,
                source="cdm-lsp",
            )
        ]

    try:
        assemble_files(
            dialect,
            [file_path],
            debug=False,
            relative_path=None,
            absolute_path=None,
            realpath=False,
            macro_libraries=None,
        )
        return []
    except AssemblerException as e:
        return [assembler_exception_to_diagnostic(e, document_path=file_path, doc=doc)]
    except Exception as e:
        return [
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=0, character=1),
                ),
                message=f"Assembler error: {e}",
                severity=types.DiagnosticSeverity.Error,
                source="cdm-lsp",
            )
        ]
