# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SRTranslator is a Python library for translating subtitle files (.srt and .ass formats) using various translation services. It provides a CLI tool, a Python API, and a GUI application built with Flet.

## Installation & Setup

### Local Development

Install the package in development mode:
```bash
pip install -e .
```

Or install dependencies directly:
```bash
pip install -r requirements.txt
```

### Docker Support

Build and run via Docker:
```bash
docker build -t srtranslator .
docker run -v /path/to/subtitles:/app/subtitles srtranslator python -m srtranslator /app/subtitles/file.srt -i en -o es
```

## Common Commands

### CLI Usage

**Basic translation:**
```bash
python -m srtranslator ./path/to/file.srt -i SRC_LANG -o DEST_LANG
```

**With specific translator:**
```bash
python -m srtranslator ./path/to/file.srt -i en -o es -t deepl-scrap
python -m srtranslator ./path/to/file.srt -i en -o es -t deepl-api --auth YOUR_API_KEY
python -m srtranslator ./path/to/file.srt -i en -o es -t translatepy
python -m srtranslator ./path/to/file.srt -i en -o es -t pydeeplx --proxies
```

**With options:**
```bash
python -m srtranslator ./file.srt -i en -o es -w 60 -v  # Custom wrap limit, verbose
python -m srtranslator ./file.srt -i en -o es -s       # Show browser (for selenium translators)
```

### GUI Development

The GUI is located in `./GUI` and built with Flet (Flutter-based framework):

**Run the GUI:**
```bash
cd GUI
pip install -r requirements.txt
python main.py
```

**Package the GUI:**
```bash
cd GUI
pip install -r requirements.txt
pip install pyinstaller
flet pack main.py
cp -r ./assets ./dist/assets
```

Binaries will be in the `dist` folder. Note: There are also GitHub Actions workflows for Linux and Windows builds.

### Testing

Pytest is available but there are no test files in the repository currently.

## Architecture

### Core Components

**1. Subtitle File Classes (`srtranslator/srt_file.py`, `srtranslator/ass_file.py`)**
- `SrtFile`: Handles .srt subtitle format using the `srt` library
- `AssFile`: Handles .ass subtitle format using the `pyass` library
- Both classes share similar interfaces:
  - `__init__(filepath)`: Load subtitle file
  - `translate(translator, source_lang, dest_lang)`: Translate using provided translator
  - `wrap_lines(line_wrap_limit)`: Format subtitles with line wrapping
  - `save(filepath)`: Save translated subtitles
  - `save_backup()`: Create backup during translation (used for resume on failure)
  - `_get_next_chunk(chunk_size)`: Generator that yields subtitle chunks based on translator's max character limit
  - `_load_backup()`: Resume from `.tmp` backup file if translation was interrupted

**2. Translator Architecture (`srtranslator/translators/`)**

All translators inherit from `base.Translator` abstract class:
```python
class Translator(ABC):
    max_char: int  # Maximum characters per translation request

    @abstractmethod
    def translate(text: str, source_language: str, destination_language: str) -> str

    def quit(self)  # Cleanup resources
```

Built-in translators:
- `deepl_scrap.DeeplTranslator`: Web scraping DeepL using Selenium (default, max_char=1500)
  - Includes proxy rotation on failure/ban detection
  - Uses `selenium_utils` for browser automation
  - Headless by default (controlled by `MOZ_HEADLESS` env var)
- `deepl_api.DeeplApi`: Official DeepL API (requires API key, max_char=1500)
- `translatepy.TranslatePy`: Uses translatepy library (max_char=1e10)
- `pydeeplx.PyDeepLX`: DeepLX API wrapper with proxy support (max_char=1500)
  - Random wait times between requests (5-10 seconds)
  - Automatic retry with proxy rotation on failure (up to 10 retries)

**3. Translation Flow**

1. Load subtitle file (auto-detects .srt vs .ass)
2. Check for `.tmp` backup file to resume interrupted translation
3. Split subtitles into chunks based on translator's `max_char` limit
4. For each chunk:
   - Combine subtitle content with newlines
   - Send to translator
   - Split response back into individual subtitles
   - Update progress
5. Optionally wrap lines for better readability
6. Save result with language suffix (e.g., `file_es.srt`)
7. Clean up backup file on success

**4. Special Handling**

- **HTML tags**: Removed from subtitle content with regex `<.*?>`
- **ASS styles**: Extracted and preserved using `|` placeholder during translation, then restored
- **Line breaks**:
  - SRT: Converted to spaces before translation, restored with wrapping
  - ASS: `\N` converted to `\\\\` placeholder to survive translation
- **Dialog markers**: Lines starting with `-` preserved with `////` placeholder
- **Resume capability**: `.tmp` backup files allow resuming failed translations

### Entry Points

- **CLI**: `srtranslator/__main__.py` - Command line interface with argparse
- **Python API**: Import `SrtFile`, `AssFile` from `srtranslator` package
- **GUI**: `GUI/main.py` - Flet-based graphical interface

### Examples Directory

The `examples/` folder contains patterns for:
- `recursive_folder.py`: Processing multiple subtitle files in a directory tree
- `custom_translator.py`: How to implement custom translator classes
- `deep_api.py`: Using DeepL API with authentication
- `custom_proxy.py`: Custom proxy configuration
- `tor_service.py`: Using Tor for anonymity

## Development Notes

### Python Requirements

- Python 3.6+ (specified in setup.py)
- Key dependencies: deepl, selenium, srt, pyass, translatepy, PyDeepLX, free_proxy, webdriverdownloader

### Selenium/Browser Requirements

For web scraping translators (deepl-scrap):
- Firefox browser (geckodriver)
- Headless mode enabled by default via `MOZ_HEADLESS=1` environment variable
- Use `-s` flag to show browser window for debugging
- Docker image includes Firefox ESR and geckodriver v0.34.0

### Creating Custom Translators

Extend `srtranslator.translators.base.Translator`:
1. Set `max_char` class variable (chunk size limit)
2. Implement `translate(text, source_language, destination_language)` method
3. Optionally implement `quit()` for cleanup
4. See `examples/custom_translator.py` for reference

### Language Codes

Language codes must match the translator being used:
- DeepL: Uses ISO codes like "en", "es", "de", with variants like "en-US", "en-GB", "pt-BR"
- TranslatePy: More flexible, supports various formats
- Use "auto" for automatic source language detection (where supported)

### Error Handling

- Translation failures trigger backup save to `.tmp` file
- Selenium-based translators auto-rotate proxies on ban detection
- PyDeepLX includes retry logic with proxy rotation
- TimeOutException raised after 60 seconds without translation response

### GUI Architecture

- Built with Flet (Python Flutter framework)
- Assets in `GUI/assets/`: language JSON files, screenshots
- Packaged with `flet pack` + manual asset copy
- CI/CD: GitHub Actions build workflows for Windows and Linux
