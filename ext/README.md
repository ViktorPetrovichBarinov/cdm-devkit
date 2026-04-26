[English](./README.md) | [Русский](./README.ru.md)

# CDM16 LSP: Syntax Highlighting

VSCode extension for CdM assembly syntax highlighting powered by a Python LSP server (`pygls`).

Current focus is `cdm8` highlighting via **Semantic Tokens**.

## What This Extension Highlights

The server classifies and returns semantic tokens for:

- `comment` — line comments (`# ...`)
- `keyword` — assembler keywords/directives control words (`asect`, `if`, `end`, ...)
- `macro` — macro definitions and macro calls
- `type` — labels and label references
- `function` — instruction mnemonics
- `parameter` — registers (`r0`, `r1`, ...)
- `number` — numeric literals (`0x..`, `0b..`, decimal)
- `string` — string/char literals

## How Highlighting Works

1. VSCode opens a source file handled by the extension.
2. The extension starts Python LSP server (`server/src/server.py`).
3. On `textDocument/semanticTokens/full`, the server tokenizes text using `cocas` lexer:
   - `cocas.assembler.generated.AsmLexer`
4. The server maps lexer tokens + target metadata to semantic token types:
   - macros from `standard.mlb`
   - directives from target `assembly_directives()`
   - instructions from target handlers
5. VSCode theme maps semantic token types to colors.

Implementation file: `server/src/semantic_tokens.py`

## Dialect

Dialect is controlled by VSCode setting:

- `cdm.dialect`: `cdm8 | cdm8e | cdm16 | cdm16e`

At the moment, highlighting behavior is tuned primarily for `cdm8`.

## User Color Customization

Users can override colors in **User Settings (JSON)**:

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

Theme-specific overrides are also supported via:

- `[Default Dark+]`
- `[Default Light+]`
- `[Default High Contrast]`
- `[Default High Contrast Light]`

inside `editor.semanticTokenColorCustomizations`.

## Development

### 1) Python dependencies

From `ext/`:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2) Client dependencies

From `ext/client/`:

```bash
npm install
npm run compile
```

### 3) Run extension in Extension Host

- Open `ext/` in VSCode
- Run `Build & Run Extension` (F5)

## Settings

Extension settings in `client/package.json`:

- `cdm.dialect` — target dialect for server features
- `cdm.pythonPath` — explicit Python interpreter path (optional)
- `cdm.autoInstall` — auto-create private venv and install deps (default: `true`)

## Notes

- Semantic highlighting requires VSCode semantic tokens support (enabled by default in modern VSCode).
- Final colors always depend on active theme + user overrides.
- If highlighting looks stale after changes, run `Developer: Reload Window`.
