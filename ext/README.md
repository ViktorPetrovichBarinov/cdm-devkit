[English](./README.md) | [Русский](./README.ru.md)

# CDM LSP (VS Code)

VS Code extension for **CdM family assembly** (`.asm`, `.mlb`) with a Python language server (`pygls`). The server uses **`cocas`** (via the **`cdm-devkit`** package in `requirements.txt`): ANTLR grammars and targets `cdm8`, `cdm8e`, `cdm16`, `cdm16e`.

## Features

| Feature | Description |
|--------|-------------|
| **Semantic highlighting** | Entity-based colors via `textDocument/semanticTokens/full` (keywords, macros, directives, mnemonics, registers, numbers, strings, labels, comments). |
| **Hover** | Markdown help from `server/data/<dialect>_mnemonics.json` (fully populated for **`cdm8e`**; stubs for `cdm8`, `cdm16`, `cdm16e`). |
| **Completion** | Prefix completion for grammar keywords, target mnemonics/directives, standard-library macro names, and JSON keys when present. |
| **Diagnostics** | On **save** of `*.asm`, runs **`cocas` assembler** for the current `cdm.dialect`; first error is published as a **red squiggle** on the reported line (whole-line span; see implementation notes). |

Dialect for all of the above is **`cdm.dialect`** (`cdm8` \| `cdm8e` \| `cdm16` \| `cdm16e`).

## Semantic token types

The server maps the grammar + target metadata to these token types (theme rules use these names):

- `comment` — `# ...` (scanned in raw text; lexer skips comments)
- `keyword` — `asect`, `if`, `end`, `is`, `else`, …
- `macro` — standard macros from `standard.mlb`, local macro definitions/calls where detected, `save` / `restore` on 8-bit targets
- `type` — labels (declarations and references in expressions)
- `function` — instruction mnemonics
- `parameter` — registers
- `number` — numeric literals
- `string` — string / character literals

Implementation: `server/src/semantic_tokens.py`.

## Hover reference JSON

Editable source of truth per dialect:

- `server/data/cdm8e_mnemonics.json` — full set of entries (`description`, `syntax`, `example`, optional `category`)
- `server/data/cdm8_mnemonics.json`, `cdm16_mnemonics.json`, `cdm16e_mnemonics.json` — placeholders for future content

The server reloads JSON when the file changes (mtime). Implementation: `server/src/hover_help.py`.

## Assembler diagnostics (errors on save)

After save, the server calls `cocas.assembler.assemble_files` on the **file on disk** for the active dialect. If assembly raises `AssemblerException`, a diagnostic is sent for the **document URI** at the reported **1-based line** (converted to LSP 0-based), spanning the full line. If the error refers to another path (e.g. macro library), the message is shown at the start of the current file and includes `location: path:line`.

Implementation: `server/src/assemble_diagnostics.py`.

## Project layout

```
ext/
  client/                 # TypeScript VS Code extension (launches the server)
  server/
    src/
      server.py           # LSP entry: initialize, didSave, semantic tokens, hover, completion, diagnostics
      semantic_tokens.py
      hover_help.py
      asm_completion.py
      assemble_diagnostics.py
      ast_utils.py        # optional AST logging (dev)
      cst_utils.py
    data/
      *_mnemonics.json   # hover (and completion key hints for filled JSONs)
  requirements.txt
```

## Development

### Python (server + cocas)

From `ext/`:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

`requirements.txt` installs **`cdm-devkit`** (includes **`cocas`** and assembler dependencies).

### Client (TypeScript)

From `ext/client/`:

```bash
npm install
npm run compile
```

### Run in Extension Host

- Open `ext/` in VS Code / Cursor
- **Run and Debug** → launch **Extension** (F5)

## Settings (`client/package.json`)

| Setting | Purpose |
|--------|---------|
| `cdm.dialect` | `cdm8` \| `cdm8e` \| `cdm16` \| `cdm16e` — target for highlighting, hover keys, completion, diagnostics |
| `cdm.pythonPath` | Optional path to Python; otherwise the Python extension’s interpreter |
| `cdm.autoInstall` | If `true`, create/update a private venv and `pip install -r requirements.txt` under global storage |

## User color customization

Override semantic token colors in **User Settings (JSON)**:

```json
{
  "editor.semanticTokenColorCustomizations": {
    "enabled": true,
    "rules": {
      "comment": "#6A9955",
      "keyword": "#C586C0",
      "macro": "#DCDCAA",
      "type": "#4FC1FF",
      "function": "#D19A66",
      "parameter": "#00D4FF",
      "number": "#B5CEA8",
      "string": "#CE9178"
    }
  }
}
```

Theme-scoped overrides work via `[Default Dark+]`, `[Default Light+]`, etc.

## Notes

- Semantic highlighting needs client support for semantic tokens (on by default in current VS Code / Cursor).
- Diagnostics run on **save** and use the **saved** file contents.
- Changing **`cdm.dialect`** is picked up via `workspace/didChangeConfiguration` (no reload). After **server or extension code** changes, use **Developer: Reload Window** if the UI looks stale.
