from __future__ import annotations

import re
from typing import Optional

from lsprotocol import types

from hover_help import word_at_cursor


def _identifier_pattern(word: str) -> re.Pattern[str]:
    escaped = re.escape(word)
    return re.compile(rf"(?<![A-Za-z0-9_.]){escaped}(?![A-Za-z0-9_.])")


def document_highlights(
    lines: list[str],
    *,
    line: int,
    character: int,
) -> Optional[list[types.DocumentHighlight]]:
    """
    All whole-identifier occurrences of the token under the cursor (same rules as hover word boundaries).
    """
    if line < 0 or line >= len(lines):
        return None
    row = lines[line]
    word = word_at_cursor(row, character)
    if not word:
        return None
    pat = _identifier_pattern(word)
    out: list[types.DocumentHighlight] = []
    for i, text in enumerate(lines):
        for m in pat.finditer(text):
            out.append(
                types.DocumentHighlight(
                    range=types.Range(
                        start=types.Position(line=i, character=m.start()),
                        end=types.Position(line=i, character=m.end()),
                    ),
                    kind=types.DocumentHighlightKind.Text,
                )
            )
    return out
