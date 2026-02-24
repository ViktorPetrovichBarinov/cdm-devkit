from datetime import datetime
from lsprotocol import types
from pygls.cli import start_server
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument

import hover_utils
import logging
import re

from lsprotocol import types

from pygls.cli import start_server
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument

ADDITION = re.compile(r"^\s*(\d+)\s*\+\s*(\d+)\s*=\s*(\d+)?$")

class InstructionInfo:
    def __init__(self, instruction: str, description: str, flags: str, affection: str, size: int):
        self.instruction = instruction        # Поле для инструкции
        self.description = description        # Поле для описания
        self.flags = flags                    # Поле для флагов
        self.affection = affection            # Поле для влияния
        self.size = size                      # Поле для размера (в байтах)

    def __repr__(self):
        return (f"InstructionInfo(instruction='{self.instruction}', "
                f"description='{self.description}', flags='{self.flags}', "
                f"affection='{self.affection}', size={self.size})")

class PullDiagnosticServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostics = {}

    def parse(self, document: TextDocument):
        _, previous = self.diagnostics.get(document.uri, (0, []))
        diagnostics = []
        
        res = hover_utils.get_syntax_tree([document.uri])
        if (len(res) != 0):
            message = res[1]
            idx = res[0] - 1
            diagnostics.append(
                types.Diagnostic(
                        message=message,
                        severity=types.DiagnosticSeverity.Error,
                        range=types.Range(
                            start=types.Position(line=idx, character=0),
                            end=types.Position(line=idx, character=100),
                        ),
                    )
                )
        
        if previous != diagnostics:
            self.diagnostics[document.uri] = (document.version, diagnostics)


server = PullDiagnosticServer("diagnostic-server", "v1")

@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: PullDiagnosticServer, params: types.DidOpenTextDocumentParams):
    """Parse each document when it is opened"""
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.parse(doc)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: PullDiagnosticServer, params: types.DidOpenTextDocumentParams):
    """Parse each document when it is changed"""
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.parse(doc)

@server.feature(
    types.TEXT_DOCUMENT_DIAGNOSTIC,
    types.DiagnosticOptions(
        identifier="pull-diagnostics",
        inter_file_dependencies=False,
        workspace_diagnostics=False,
    ),
)
def diagnostic(ls: PullDiagnosticServer, params: types.DocumentDiagnosticParams):
    if (uri := params.text_document.uri) not in ls.diagnostics:
        return

    version, diagnostics = ls.diagnostics[uri]
    result_id = f"{uri}@{version}"

    if result_id == params.previous_result_id:
        return types.UnchangedDocumentDiagnosticReport(result_id)

    return types.FullDocumentDiagnosticReport(items=diagnostics, result_id=result_id)

instruction_map = {
    "ldw": InstructionInfo(
        instruction="ldw rs, rd",
        description="Load word. Loads 2 bytes from data memory pointed by rs to rd.",
        flags="-",
        affection="1-2",
        size=2
    ),
    "ldb": InstructionInfo(
        instruction="ldb rs, rd",
        description="Load byte. Loads a byte from data memory pointed by rs to rd.",
        flags="-",
        affection="1-2",
        size=2
    ),
    "ldsb": InstructionInfo(
        instruction="ldsb rs, rd",
        description="Load signed byte. Loads a byte from data memory pointed by rs to rd with sign-extend.",
        flags="-",
        affection="1-2",
        size=2
    )
}

# DATE_FORMATS = [
#     "%H:%M:%S",
#     "%d/%m/%y",
#     "%Y-%m-%d",
#     "%Y-%m-%dT%H:%M:%S",
# ]

# @server.feature(
#     types.TEXT_DOCUMENT_COMPLETION,
#     types.CompletionOptions(trigger_characters=["."]),
# )
# def completions(params: types.CompletionParams):
#     document = server.workspace.get_text_document(params.text_document.uri)
#     current_line = document.lines[params.position.line].strip()

#     if not current_line.endswith("Hello."):
#         return []

#     return [
#         types.CompletionItem(label="from server"),
#         types.CompletionItem(label="how are you?"),
#         types.CompletionItem(label="world."),
#     ]

def get_word_at_cursor(line: str, cursor_position: int) -> str:
    # Удаляем пробелы в начале и конце строки
    line = line.strip()
    
    # Если позиция курсора вне диапазона, возвращаем None
    if cursor_position < 0 or cursor_position >= len(line):
        return None

    # Разделяем строку на слова по пробелам
    words = line.split()
    
    # Пока не найдём слово, будем искать
    current_position = 0
    for word in words:
        # Длина слова + пробел (если не последнее слово)
        word_length = len(word)
        
        # Если позиция курсора внутри текущего слова
        if current_position <= cursor_position < current_position + word_length:
            return word
        
        # Переход на следующее слово
        current_position += word_length + 1  # +1 для пробела

    return None


@server.feature(
    types.TEXT_DOCUMENT_HOVER
)
def hover(ls: LanguageServer, params: types.HoverParams):
    pos = params.position
    
    document_uri = params.text_document.uri
    document = ls.workspace.get_text_document(document_uri)

    try:
        line = document.lines[pos.line]
    except IndexError:
        return None
    word = get_word_at_cursor(line, pos.character)
    instruction_info = instruction_map[word]
    

    hover_content = [
        f"# Инструкция: {instruction_info.instruction}",
        "",
        f"**Описание:** {instruction_info.description}\n",
        f"**Флаги:** {instruction_info.flags}\n",
        f"**Влияние:** {instruction_info.affection}\n",
        f"**Размер:** {instruction_info.size} байт\n",
    ]
    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value="\n".join(hover_content),
        ),
        range=types.Range(
            start=types.Position(line=pos.line, character=0),
            end=types.Position(line=pos.line + 1, character=0),
        ),
    )

if __name__ == "__main__":
    server.start_io()