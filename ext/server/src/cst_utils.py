from __future__ import annotations

from pathlib import Path

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from cocas.assembler.generated import AsmLexer, AsmParser


class _SilentErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        return


def cst_to_string(source: str) -> str:
    """
    Build a best-effort parse tree (CST) string for an editor buffer.

    Notes:
    - Works on in-memory text (no filesystem access).
    - Appends a virtual `end` to tolerate incomplete buffers.
    - Suppresses ANTLR default error output.
    """
    parse_text = source
    if not parse_text.endswith("\n"):
        parse_text += "\n"
    parse_text += "end\n"

    lexer = AsmLexer(InputStream(parse_text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_SilentErrorListener())
    token_stream = CommonTokenStream(lexer)
    token_stream.fill()

    parser = AsmParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(_SilentErrorListener())

    tree = parser.program_nomacros()
    return tree.toStringTree(recog=parser)


def cst_file_to_string(filepath: Path) -> str:
    """
    Read a file from disk and return its ANTLR CST string.

    This is useful for didSave handlers where we want to log
    the syntactic structure of the actual saved file contents.
    """
    source = filepath.read_text(encoding="utf-8")
    return cst_to_string(source)

