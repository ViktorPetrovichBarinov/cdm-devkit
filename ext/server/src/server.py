import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

from pygls.lsp.server import LanguageServer
from lsprotocol import types

from assemble_diagnostics import build_assemble_diagnostics
from asm_completion import completion_list
from ast_utils import ast_file_to_string
from cst_utils import cst_file_to_string
from document_highlights import document_highlights as build_document_highlights
from hover_help import hover_for_word, word_at_cursor
from semantic_tokens import legend as semantic_legend, semantic_tokens_full

server = LanguageServer("CDM-server", "v0.1")
_dialect: str = "cdm16"


@server.feature(types.INITIALIZE)
def on_initialize(params: types.InitializeParams):
    global _dialect
    opts = params.initialization_options or {}
    if isinstance(opts, dict) and opts.get("dialect"):
        _dialect = str(opts["dialect"])
    logging.info("Initialized with dialect=%s", _dialect)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: types.DidSaveTextDocumentParams):
    uri = params.text_document.uri
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        logging.warning("didSave: unsupported URI scheme %s", parsed.scheme)
        return

    file_path = Path(unquote(parsed.path))
    doc = server.workspace.get_text_document(uri)

    # Assembler diagnostics (cocas): one failing error ends the build — show that line/range.
    if file_path.suffix.lower() == ".asm":
        diags = build_assemble_diagnostics(file_path, doc, _dialect)
        try:
            server.protocol.notify(
                types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS,
                types.PublishDiagnosticsParams(
                    uri=uri,
                    diagnostics=diags,
                    version=doc.version,
                ),
            )
        except Exception:
            logging.exception("Failed to publish diagnostics for %s", uri)

    try:
        cst = cst_file_to_string(file_path)
        logging.info("CST for %s\n%s", file_path.as_posix(), cst)

        ast = ast_file_to_string(file_path, target=_dialect)
        logging.info("AST for %s (target=%s)\n%s", file_path.as_posix(), _dialect, ast)
    except Exception as e:
        logging.exception("Failed to build CST for %s: %s", params.text_document.uri, e)


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    types.SemanticTokensRegistrationOptions(
        legend=semantic_legend,
        full=True,
        range=False,
        document_selector=[
            {"scheme": "file", "pattern": "**/*.asm"},
            {"scheme": "file", "pattern": "**/*.mlb"},
        ],
    ),
)
def semantic_tokens_full_handler(params: types.SemanticTokensParams) -> types.SemanticTokens:
    doc = server.workspace.get_text_document(params.text_document.uri)
    return semantic_tokens_full(doc.source, uri=params.text_document.uri, target=_dialect)


@server.feature(
    types.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT,
    types.DocumentHighlightRegistrationOptions(
        document_selector=[
            {"scheme": "file", "pattern": "**/*.asm"},
            {"scheme": "file", "pattern": "**/*.mlb"},
        ],
    ),
)
def document_highlight(params: types.DocumentHighlightParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    lines = list(doc.lines)
    return build_document_highlights(
        lines,
        line=params.position.line,
        character=params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_HOVER, types.HoverOptions())
def hover(params: types.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    try:
        line = doc.lines[params.position.line]
    except IndexError:
        return None
    word = word_at_cursor(line, params.position.character)
    if not word:
        return None
    return hover_for_word(word, dialect=_dialect)


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(resolve_provider=False),
)
def completions(params: types.CompletionParams):
    document = server.workspace.get_text_document(params.text_document.uri)
    try:
        line_text = document.lines[params.position.line]
    except IndexError:
        return types.CompletionList(is_incomplete=False, items=[])
    return completion_list(
        line_text=line_text,
        line=params.position.line,
        character=params.position.character,
        dialect=_dialect,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    server.start_io()