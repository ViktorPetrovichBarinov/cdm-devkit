from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener
from lsprotocol import types

from cocas.assembler.generated import AsmLexer, AsmParser, AsmParserVisitor
from cocas.assembler.macro_processor import MacroDefinition, read_mlb
from cocas.assembler.targets import import_target, standard_mlb


TOKEN_TYPES: list[str] = [
    # Keep this small and stable; VSCode maps these to colors.
    "comment",
    "keyword",
    "macro",
    "type",  # labels
    "function",  # instruction mnemonics
    "parameter",  # registers
    "number",
    "string",
]

TOKEN_TYPE_TO_INDEX = {t: i for i, t in enumerate(TOKEN_TYPES)}

# NOTE: legend must be an lsprotocol object (not a dict), otherwise server capabilities
# serialization fails (cattrs expects .token_types / .token_modifiers attributes).
legend = types.SemanticTokensLegend(token_types=TOKEN_TYPES, token_modifiers=[])


@dataclass(frozen=True)
class _Tok:
    line: int  # 0-based
    col: int  # 0-based
    length: int
    token_type: int
    token_mods: int = 0


def _encode(tokens: list[_Tok]) -> list[int]:
    # LSP SemanticTokens: [deltaLine, deltaStart, length, tokenType, tokenModifiers]...
    tokens.sort(key=lambda t: (t.line, t.col))
    data: list[int] = []
    prev_line = 0
    prev_col = 0
    for t in tokens:
        dl = t.line - prev_line
        dc = t.col - (prev_col if dl == 0 else 0)
        data.extend([dl, dc, t.length, t.token_type, t.token_mods])
        prev_line = t.line
        prev_col = t.col
    return data


class _SilentErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        # Never raise from semantic highlighting; keep it best-effort.
        return


def _iter_comment_spans(text: str) -> Iterable[tuple[int, int, int]]:
    """
    Yield (line0, col0, length) for '#' comments.

    The assembler lexer skips COMMENT tokens, so for editor highlighting we scan the raw text.
    We try to avoid treating '#' inside quotes as a comment, with a small state machine.
    """
    for line0, line in enumerate(text.splitlines()):
        in_s = False
        in_d = False
        esc = False
        for i, ch in enumerate(line):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if not in_d and ch == "'":
                in_s = not in_s
                continue
            if not in_s and ch == '"':
                in_d = not in_d
                continue
            if not in_s and not in_d and ch == "#":
                yield (line0, i, len(line) - i)
                break


def _load_standard_macros(target: str) -> dict[str, dict[int, MacroDefinition]]:
    # standard_mlb(target) points into cocas package targets.
    return read_mlb(standard_mlb(target))


def _load_local_macro_names(text: str, filepath: str) -> set[str]:
    """
    Parse the file with Macro.g4 to find macro definitions in the current file.
    We only need names for highlighting (not bodies).
    """
    from antlr4 import CommonTokenStream

    from cocas.assembler.generated import MacroLexer, MacroParser

    src = text if text.endswith("\n") else text + "\n"
    lexer = MacroLexer(InputStream(src))
    token_stream = CommonTokenStream(lexer)
    parser = MacroParser(token_stream)
    tree = parser.program()

    names: set[str] = set()

    # Walk the parse tree without relying on generated visitor base classes
    # (keep it robust across regenerations).
    def walk(node):
        # Macro header: 'macro' NAME '/' DIGIT
        if node.__class__.__name__ == "MacroContext":
            header = getattr(node, "macro_header", lambda: None)()
            if header is not None:
                name_tok = getattr(header, "NAME", lambda: None)()
                if name_tok is not None:
                    names.add(name_tok.getText())
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(tree)
    _ = filepath
    return names


class _AsmEntityVisitor(AsmParserVisitor):
    def __init__(
        self,
        token_stream: CommonTokenStream,
        keywords: set[str],
        directives: set[str],
        macro_names: set[str],
    ):
        super().__init__()
        self._ts = token_stream
        self._keywords = keywords
        self._directives = directives
        self._macro_names = macro_names
        self.tokens: list[_Tok] = []
        # Keyword-like terminals in the lexer grammar.
        # Highlight these regardless of where they appear in the CST.
        self._keyword_token_types: set[int] = {
            AsmLexer.Asect,
            AsmLexer.Break,
            AsmLexer.Continue,
            AsmLexer.Do,
            AsmLexer.Else,
            AsmLexer.End,
            AsmLexer.Ext,
            AsmLexer.Fi,
            AsmLexer.If,
            AsmLexer.Is,
            AsmLexer.Macro,
            AsmLexer.Rsect,
            AsmLexer.Stays,
            AsmLexer.Then,
            AsmLexer.Tplate,
            AsmLexer.Until,
            AsmLexer.Wend,
            AsmLexer.While,
        }

    def _add_tok(self, tok, token_type: str):
        if tok is None:
            return
        t = TOKEN_TYPE_TO_INDEX[token_type]
        line0 = int(tok.line) - 1
        col0 = int(getattr(tok, "column", 0) or 0)
        text = tok.text or ""
        if line0 >= 0 and len(text) > 0:
            self.tokens.append(_Tok(line0, col0, len(text), t))

    def _add_terminal(self, term, token_type: str):
        # term is a TerminalNodeImpl (from antlr4); getSymbol() is the token.
        if term is None:
            return
        tok = getattr(term, "symbol", None) or getattr(term, "getSymbol", lambda: None)()
        self._add_tok(tok, token_type)

    def visitTerminal(self, node):  # noqa: N802
        """
        Catch-all for keyword terminals like 'asect', 'end', 'if', 'else', ...
        """
        tok = getattr(node, "symbol", None) or getattr(node, "getSymbol", lambda: None)()
        if tok is not None and getattr(tok, "type", None) in self._keyword_token_types:
            self._add_tok(tok, "keyword")
        return super().visitTerminal(node)

    def visitProgram_nomacros(self, ctx: AsmParser.Program_nomacrosContext):
        # Highlight final 'end'
        try:
            self._add_terminal(getattr(ctx, "End", lambda: None)(), "keyword")
        except Exception:
            pass
        return self.visitChildren(ctx)

    def visitAsect_header(self, ctx: AsmParser.Asect_headerContext):
        self._add_tok(ctx.start, "keyword")  # 'asect'
        return self.visitChildren(ctx)

    def visitRsect_header(self, ctx: AsmParser.Rsect_headerContext):
        self._add_tok(ctx.start, "keyword")  # 'rsect'
        return self.visitChildren(ctx)

    def visitTplate_header(self, ctx: AsmParser.Tplate_headerContext):
        self._add_tok(ctx.start, "keyword")  # 'tplate'
        return self.visitChildren(ctx)

    def visitBreak_statement(self, ctx: AsmParser.Break_statementContext):
        self._add_tok(ctx.start, "keyword")  # 'break'
        return self.visitChildren(ctx)

    def visitContinue_statement(self, ctx: AsmParser.Continue_statementContext):
        self._add_tok(ctx.start, "keyword")  # 'continue'
        return self.visitChildren(ctx)

    def visitConditional(self, ctx: AsmParser.ConditionalContext):
        # if ... else ... fi
        self._add_tok(ctx.start, "keyword")  # 'if'
        # Else/Fi/Then/Is are handled in their specific contexts too,
        # but we keep Fi here since it's always present.
        self._add_terminal(getattr(ctx, "Fi", lambda: None)(), "keyword")
        return self.visitChildren(ctx)

    def visitConditions(self, ctx: AsmParser.ConditionsContext):
        # optional "then" keyword at the end of conditions
        self._add_terminal(getattr(ctx, "Then", lambda: None)(), "keyword")
        return self.visitChildren(ctx)

    def visitCondition(self, ctx: AsmParser.ConditionContext):
        # "... is <branch_mnemonic>"
        self._add_terminal(getattr(ctx, "Is", lambda: None)(), "keyword")
        return self.visitChildren(ctx)

    def visitElse_clause(self, ctx: AsmParser.Else_clauseContext):
        # "else" starts the clause
        self._add_tok(ctx.start, "keyword")
        return self.visitChildren(ctx)

    def visitWhile_loop(self, ctx: AsmParser.While_loopContext):
        self._add_tok(ctx.start, "keyword")  # 'while'
        self._add_terminal(getattr(ctx, "Stays", lambda: None)(), "keyword")
        self._add_terminal(getattr(ctx, "Wend", lambda: None)(), "keyword")
        return self.visitChildren(ctx)

    def visitUntil_loop(self, ctx: AsmParser.Until_loopContext):
        self._add_tok(ctx.start, "keyword")  # 'do'
        self._add_terminal(getattr(ctx, "Until", lambda: None)(), "keyword")
        return self.visitChildren(ctx)

    # label declarations: (labels_declaration (labels (label (name ...))) :)
    def visitLabels_declaration(self, ctx: AsmParser.Labels_declarationContext):
        labels_ctx = ctx.labels()
        for lab in labels_ctx.label():
            name_ctx = lab.name()
            self._add_tok(name_ctx.start, "type")
        return self.visitChildren(ctx)

    # instruction: single WORD-like token
    def visitInstruction(self, ctx: AsmParser.InstructionContext):
        tok = ctx.start
        if tok is None:
            return self.visitChildren(ctx)
        text = tok.text or ""
        low = text.lower()

        if low in self._keywords or low in self._directives:
            self._add_tok(tok, "keyword")
        elif low in {"save", "restore"}:
            # In some dialects these are implemented as macros/pseudo-ops.
            self._add_tok(tok, "macro")
        elif low in self._macro_names:
            self._add_tok(tok, "macro")
        else:
            self._add_tok(tok, "function")
        return self.visitChildren(ctx)

    def visitRegister(self, ctx: AsmParser.RegisterContext):
        self._add_tok(ctx.start, "parameter")
        return self.visitChildren(ctx)

    def visitByte_specifier(self, ctx: AsmParser.Byte_specifierContext):
        # low(expr) / high(expr) — assembler byte specifiers (cdm8e)
        self._add_tok(ctx.start, "keyword")
        return self.visitChildren(ctx)

    def visitNumber(self, ctx: AsmParser.NumberContext):
        self._add_tok(ctx.start, "number")
        return self.visitChildren(ctx)

    def visitString(self, ctx: AsmParser.StringContext):
        self._add_tok(ctx.start, "string")
        return self.visitChildren(ctx)

    def visitCharacter(self, ctx: AsmParser.CharacterContext):
        self._add_tok(ctx.start, "string")
        return self.visitChildren(ctx)

    # label references inside expressions: (label (name ...))
    def visitLabel(self, ctx: AsmParser.LabelContext):
        name_ctx = ctx.name()
        self._add_tok(name_ctx.start, "type")
        return self.visitChildren(ctx)


def semantic_tokens_full(text: str, *, uri: str, target: str) -> types.SemanticTokens:
    """
    Compute semantic tokens for one document.

    We use:
    - CST (AsmParser.program_nomacros) for structural positions (instructions/labels/regs/numbers/strings/keywords)
    - Macro.g4 for local macro definitions
    - standard.mlb for standard macro names
    - raw scanning for comments ('# ...')
    """
    parsed = Path(uri) if "://" not in uri else None
    filepath_hint = parsed.as_posix() if parsed else uri

    # Load macro names (standard + local).
    macro_names: set[str] = set()
    try:
        std = _load_standard_macros(target)
        macro_names |= set(std.keys())
    except Exception:
        # If target isn't available, still highlight local macros etc.
        pass
    try:
        macro_names |= _load_local_macro_names(text, filepath_hint)
    except Exception:
        pass

    # Keywords/directives.
    keywords = {
        "asect",
        "rsect",
        "tplate",
        "macro",
        "mend",
        "end",
        "if",
        "then",
        "else",
        "fi",
        "while",
        "wend",
        "until",
        "do",
        "break",
        "continue",
        "stays",
        "ext",
        "is",
    }
    # byte specifiers (cdm8e)
    keywords |= {"low", "high"}

    directives = {"ds", "dc", "db", "dw", "align"}
    try:
        ti = import_target(target)
        directives |= set(ti.assembly_directives())
        directives.add("align")
    except Exception:
        pass

    visitor_tokens: list[_Tok] = []

    # Parse CST (best-effort). If parsing fails for an incomplete buffer (e.g. no `end`),
    # fall back to lexer-based highlighting.
    try:
        parse_text = text
        if not parse_text.endswith("\n"):
            parse_text += "\n"
        # Make the grammar tolerant to incomplete buffers.
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

        v = _AsmEntityVisitor(token_stream, keywords, directives, macro_names)
        v.visit(tree)
        visitor_tokens.extend(v.tokens)
    except Exception:
        # Fallback: use lexer tokens directly on the raw text (no virtual 'end').
        lx = AsmLexer(InputStream(text if text.endswith("\n") else text + "\n"))
        lx.removeErrorListeners()
        lx.addErrorListener(_SilentErrorListener())
        ts = CommonTokenStream(lx)
        ts.fill()
        for tok in ts.tokens:
            if tok is None or tok.text is None:
                continue
            # Skip virtual EOF and skipped channels (WS/COMMENT are skipped in lexer anyway).
            if tok.type <= 0:
                continue
            line0 = int(tok.line) - 1
            col0 = int(getattr(tok, "column", 0) or 0)
            ttext = tok.text
            low = ttext.lower()

            if tok.type == AsmLexer.REGISTER:
                visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["parameter"]))
            elif tok.type in (AsmLexer.DECIMAL_NUMBER, AsmLexer.HEX_NUMBER, AsmLexer.BINARY_NUMBER):
                visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["number"]))
            elif tok.type in (AsmLexer.STRING, AsmLexer.CHAR):
                visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["string"]))
            elif tok.type in (AsmLexer.Asect, AsmLexer.Rsect, AsmLexer.Tplate, AsmLexer.End,
                              AsmLexer.If, AsmLexer.Then, AsmLexer.Else, AsmLexer.Fi,
                              AsmLexer.While, AsmLexer.Wend, AsmLexer.Do, AsmLexer.Until,
                              AsmLexer.Break, AsmLexer.Continue, AsmLexer.Ext, AsmLexer.Is, AsmLexer.Stays,
                              AsmLexer.Macro):
                visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["keyword"]))
            elif tok.type in (AsmLexer.WORD, AsmLexer.WORD_WITH_DOTS):
                if low in directives or low in keywords:
                    visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["keyword"]))
                elif low in {"save", "restore"} or low in macro_names:
                    visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["macro"]))
                else:
                    # Best-effort: treat as mnemonic/identifier
                    visitor_tokens.append(_Tok(line0, col0, len(ttext), TOKEN_TYPE_TO_INDEX["function"]))

    # Comments (raw scan) — do this on original text to keep positions accurate.
    for line0, col0, length in _iter_comment_spans(text):
        visitor_tokens.append(_Tok(line0, col0, length, TOKEN_TYPE_TO_INDEX["comment"]))

    return types.SemanticTokens(data=_encode(visitor_tokens))

