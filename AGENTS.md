# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Quick Reference

| Command | Description |
|---------|-------------|
| `make install` | Install all dependencies with uv |
| `make fmt` | Format code with ruff |
| `make check` | Run linting and type checking |
| `make test` | Run pytest test suite |
| `make upgrade` | Upgrade all dependencies to latest |
| `make build` | Build package distribution |
| `make clean` | Remove build artifacts |

## Important: STRICTLY use uv

This project uses **uv** as the package manager. Do NOT use pip, pipenv, or poetry.

```bash
# Install dependencies
make install
# or: uv sync --all-extras

# Run any Python command
uv run python -m srtranslator ...
uv run pytest
uv run ruff check
```

## Project Overview

SRTranslator is a Python library for translating subtitle files (.srt and .ass formats) using various translation services. It provides a CLI tool and a Python API.

## Project Structure

```
SRTranslator/
├── srtranslator/           # Main package
│   ├── __init__.py
│   ├── __main__.py         # CLI entry point
│   ├── srt_file.py         # SRT subtitle handling
│   ├── ass_file.py         # ASS subtitle handling
│   ├── util.py             # Utility functions
│   └── translators/        # Translator implementations
│       ├── base.py         # Abstract base class
│       ├── deepl_api.py    # Official DeepL API
│       ├── deepl_scrap.py  # DeepL web scraping
│       ├── pydeeplx.py     # DeepLX wrapper
│       ├── translatepy.py  # translatepy library
│       └── selenium_utils.py
├── tests/                  # Test suite
├── examples/               # Usage examples
├── docs/                   # Documentation
├── pyproject.toml          # Project configuration
├── Makefile               # Build commands
└── uv.lock                # Dependency lock file
```

## Code Style Guidelines

- **Line length**: 100 characters max
- **Python version**: 3.12 target
- **Linting**: ruff with I (isort), UP (pyupgrade), B (bugbear) rules
- **Type checking**: basedpyright in standard mode
- **Formatting**: ruff format

## Development Workflow

```bash
# Initial setup
make install

# Before committing
make fmt      # Auto-fix formatting issues
make check    # Verify linting and types
make test     # Run tests

# Full verification
make          # Runs install, check, test
```

## CLI Usage

```bash
# Basic translation
uv run srtranslator ./path/to/file.srt -i en -o es

# With specific translator
uv run srtranslator ./file.srt -i en -o es -t deepl-api --auth YOUR_API_KEY
uv run srtranslator ./file.srt -i en -o es -t translatepy
uv run srtranslator ./file.srt -i en -o es -t pydeeplx --proxies
```

## Architecture

### Core Components

**Subtitle File Classes** (`srt_file.py`, `ass_file.py`):
- `SrtFile`: Handles .srt format using `srt` library
- `AssFile`: Handles .ass format using `pyass` library

**Translator Architecture** (`translators/`):
All translators inherit from `base.Translator`:
```python
class Translator(ABC):
    max_char: int  # Maximum characters per request

    @abstractmethod
    def translate(text: str, source_language: str, destination_language: str) -> str

    def quit(self)  # Cleanup resources
```

Built-in translators:
- `deepl_scrap.DeeplTranslator`: Web scraping via Selenium (default)
- `deepl_api.DeeplApi`: Official DeepL API via `deepl.DeepLClient` (requires key)
  - Defaults to the next-gen model (`model_type="quality_optimized"`), which has covered
    every language pair since December 2025. `--model-type` overrides it
  - A source language of `auto` is sent as no `source_lang` at all
  - `custom_instructions` (CLI `--instruction`). Verified live: DeepL enforces at most 10
    instructions of 300 characters each, and nothing else. It does **not** restrict them by
    target language (Finnish and Swedish work, and the instruction is honoured) and does
    **not** reject them with `latency_optimized`. Do not reintroduce either restriction;
    both were copied from the docs and are wrong
  - Sums `billed_characters` and logs the total plus `model_type_used` at INFO
- `translatepy.TranslatePy`: Uses translatepy library
- `pydeeplx.PyDeepLX`: DeepLX API wrapper with proxy support

## Creating Custom Translators

Extend `srtranslator.translators.base.Translator`:
1. Set `max_char` class variable
2. Implement `translate(text, source_language, destination_language)` method
3. Optionally implement `quit()` for cleanup
4. See `examples/custom_translator.py` for reference

## Gotchas

- **DeepL translates each entry of a text list independently.** Entries share only the
  `context` parameter, which is why each chunk is repeated inside its own context. Removing
  that leaves every line blind to its neighbours.
- **Context is not billed**, so budgets are generous. The hard ceiling is DeepL's 128 KiB
  request body; `util.fit_context` trims the head of the context to stay under it.
- **Never feed translated text back as context.** The backward walk in
  `_build_deepl_context` stops at `self.start_from`, because a resumed run holds
  target-language text below that index.
- **The DeepL API does not strip `\N`.** Verified live across every parameter combination,
  both models, and a bare request: a literal `\N` comes back intact. The comment claiming
  otherwise, and the placeholder machinery built on it, predate the API translator and
  presumably describe the Selenium scraper or another backend. The placeholder is kept
  because `deepl-scrap` is still the default translator and was not retested, but do not
  assume the premise holds for `deepl-api`.
- **ASS line breaks travel as a backslash placeholder.** `ass_file` swaps `\N` for
  `ASS_LINE_BREAK_PADDED` (four backslashes, space padded) and `wrap_lines` restores any run
  of two or more backslashes. Use a lambda replacement in `re.sub` for both, because a
  literal replacement string re-escapes the backslashes. The older character-class version
  ate the characters next to the placeholder and never restored `\N`.
  The encoding must stay **above** the `-` dialogue branch: that branch `continue`s, so a
  two-speaker line such as `-Are you sure?\N-Quite sure.` used to skip the placeholder
  entirely. pyass never yields a real newline in event text, so the `////` substitution in
  that branch is dead code for ASS and only the `continue` mattered.
- **`util.fit_context` measures the wire size, not UTF-8 bytes.** The client posts JSON
  through requests with `ensure_ascii=True`, so non-ASCII doubles in size. It is a backstop
  that never fires under the current context budgets.
- **`SrtFile` and `AssFile` duplicate their chunking and context logic.** A fix applied to
  one usually belongs in the other. `SrtFile` keeps a `raw_contents` map for clean context;
  `AssFile` uses `util.clean_context_line` instead.
- **`load_subtitle` tries ASS first** and falls back to SRT, so every run prints a
  "Loading as ASS" line even for SRT. That is not an error.
