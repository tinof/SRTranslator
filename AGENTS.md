# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Quick Reference

| Command | Description |
|---------|-------------|
| `make install` | Install all dependencies with uv |
| `make fmt` | Format code with ruff |
| `make check` | Run linting and type checking |
| `make test` | Run pytest test suite |
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
- `deepl_api.DeeplApi`: Official DeepL API (requires key)
- `translatepy.TranslatePy`: Uses translatepy library
- `pydeeplx.PyDeepLX`: DeepLX API wrapper with proxy support

## Creating Custom Translators

Extend `srtranslator.translators.base.Translator`:
1. Set `max_char` class variable
2. Implement `translate(text, source_language, destination_language)` method
3. Optionally implement `quit()` for cleanup
4. See `examples/custom_translator.py` for reference
