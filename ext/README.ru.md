[English](./README.md) | [Русский](./README.ru.md)

# CDM LSP: Подсветка синтаксиса

Расширение VSCode для подсветки ассемблера CdM на базе Python LSP-сервера (`pygls`).

Сейчас основной фокус — подсветка `cdm8` через **Semantic Tokens**.

## Что подсвечивается

Сервер возвращает semantic tokens для:

- `comment` — комментарии (`# ...`)
- `keyword` — ключевые слова/директивы (`asect`, `if`, `end`, ...)
- `macro` — определения и вызовы макросов
- `type` — метки и ссылки на метки
- `function` — мнемоники инструкций
- `parameter` — регистры (`r0`, `r1`, ...)
- `number` — числовые литералы (`0x..`, `0b..`, десятичные)
- `string` — строковые/символьные литералы

## Как работает подсветка

1. VSCode открывает исходный файл, который обрабатывает расширение.
2. Расширение запускает Python LSP-сервер (`server/src/server.py`).
3. На `textDocument/semanticTokens/full` сервер токенизирует текст через lexer из `cocas`:
   - `cocas.assembler.generated.AsmLexer`
4. Сервер сопоставляет лексемы и метаданные target с типами semantic tokens:
   - макросы из `standard.mlb`
   - директивы из `assembly_directives()`
   - инструкции из target handlers
5. Тема VSCode сопоставляет semantic token types с цветами.

Файл реализации: `server/src/semantic_tokens.py`

## Диалект

Диалект задается настройкой VSCode:

- `cdm.dialect`: `cdm8 | cdm8e | cdm16 | cdm16e`

На текущий момент подсветка в первую очередь настроена под `cdm8`.

## Кастомизация цветов пользователем

Пользователь может переопределить цвета в **User Settings (JSON)**:

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

Также поддерживаются theme-specific overrides:

- `[Default Dark+]`
- `[Default Light+]`
- `[Default High Contrast]`
- `[Default High Contrast Light]`

внутри `editor.semanticTokenColorCustomizations`.

## Разработка

### 1) Python-зависимости

Из `ext/`:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 2) Зависимости клиента

Из `ext/client/`:

```bash
npm install
npm run compile
```

### 3) Запуск расширения в Extension Host

- Открой `ext/` в VSCode
- Запусти `Build & Run Extension` (F5)

## Настройки

Настройки расширения в `client/package.json`:

- `cdm.dialect` — целевой диалект для server features
- `cdm.pythonPath` — явный путь к Python-интерпретатору (опционально)
- `cdm.autoInstall` — авто-создание приватного venv и установка зависимостей (по умолчанию: `true`)

## Примечания

- Для работы нужна поддержка semantic tokens в VSCode (в современных версиях включена по умолчанию).
- Финальные цвета зависят от активной темы и пользовательских overrides.
- Смена **`cdm.dialect`** подхватывается без перезагрузки окна. После правок **кода сервера/расширения** при необходимости выполни `Developer: Reload Window`.

