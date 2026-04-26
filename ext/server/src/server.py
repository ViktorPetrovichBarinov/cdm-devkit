import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

from pygls.lsp.server import LanguageServer
from lsprotocol import types

from ast_utils import ast_file_to_string
from cst_utils import cst_file_to_string
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
    try:
        # Build CST from the saved file on disk (not editor buffer).
        uri = params.text_document.uri
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"Unsupported URI scheme for didSave: {parsed.scheme}")

        file_path = Path(unquote(parsed.path))
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
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=[" "]),
)
def completions(params: types.CompletionParams):
    document = server.workspace.get_text_document(params.text_document.uri)
    current_line = document.lines[params.position.line].strip()

    if not current_line.endswith("hello."):
        return []

    return [
        types.CompletionItem(label="world"),
    ]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    server.start_io()