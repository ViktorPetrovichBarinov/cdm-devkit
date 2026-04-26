import logging

from pygls.lsp.server import LanguageServer
from lsprotocol import types

from ast_utils import try_build_and_format_ast
from semantic_tokens import legend as semantic_legend, semantic_tokens_full

server = LanguageServer("CDM-server", "v0.1")

# Глобальная переменная для хранения диалекта
current_dialect = "cdm16"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

@server.feature(types.INITIALIZE)
def initialize(params: types.InitializeParams):
    global current_dialect
    if params.initialization_options:
        current_dialect = params.initialization_options.get('dialect', 'cdm16')
    logging.info(f"CDM dialect set to: {current_dialect}")


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    semantic_legend(),
)
def semantic_tokens(params: types.SemanticTokensParams):
    document = server.workspace.get_text_document(params.text_document.uri)
    return semantic_tokens_full(document.source, current_dialect)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: types.DidSaveTextDocumentParams):
    try:
        document = server.workspace.get_text_document(params.text_document.uri)
    except Exception as e:
        logging.error("Failed to get document on save: %s", e)
        return

    ast_text, err = try_build_and_format_ast(
        document.source,
        uri=params.text_document.uri,
        dialect=current_dialect,
        max_chars=20000,
    )
    if err is not None:
        logging.error(
            "AST build failed (%s) at %s:%s: %s",
            err.tag.value if hasattr(err, "tag") else "error",
            err.file,
            err.line,
            err.description,
        )
    else:
        logging.info("AST dump for %s\n%s", params.text_document.uri, ast_text)


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=[" "]),
)
def completions(params: types.CompletionParams):
    document = server.workspace.get_text_document(params.text_document.uri)
    current_line = document.lines[params.position.line].strip()

    if current_line.endswith("ast"):
        # Triggered by a space press. Remove the trailing "ast" token from the
        # in-memory source before parsing so the command itself doesn't break parsing.
        lines = document.source.splitlines(True)  # keep line endings
        line_idx = params.position.line
        if 0 <= line_idx < len(lines):
            original = lines[line_idx]
            # remove last occurrence of 'ast' at end of line (ignoring trailing whitespace)
            stripped = original.rstrip("\r\n")
            suffix_ws = stripped[len(stripped.rstrip()):]
            core = stripped.rstrip()
            if core.endswith("ast"):
                core = core[: -len("ast")]
                lines[line_idx] = core + suffix_ws + original[len(stripped):]

        sanitized_source = "".join(lines)

        ast_text, err = try_build_and_format_ast(
            sanitized_source,
            uri=params.text_document.uri,
            dialect=current_dialect,
            max_chars=20000,
        )
        if err is not None:
            logging.error(
                "AST build failed (%s) at %s:%s: %s",
                err.tag.value if hasattr(err, "tag") else "error",
                err.file,
                err.line,
                err.description,
            )
        else:
            logging.info("AST dump for %s\n%s", params.text_document.uri, ast_text)

        return [
            types.CompletionItem(label="dumped_ast_to_log"),
            types.CompletionItem(label="(see Output: CDM-server)"),
        ]

    if not current_line.endswith("hello."):
        return []

    return [
        types.CompletionItem(label="world"),
        types.CompletionItem(label="friend"),
    ]


if __name__ == "__main__":
    server.start_io()