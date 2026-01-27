# SRTranslator

> CLI-only subtitle translator for Linux and macOS.

## Install

- pipx (recommended for CLI use):
  ```bash
  pipx install srtranslator
  ```
- pipx from this fork (installs directly from `tinof/SRTranslator`):
  ```bash
  pipx install git+https://github.com/tinof/SRTranslator.git
  ```
- pip:
  ```bash
  pip install srtranslator
  ```

## Usage in Blender

[tin2tin](https://github.com/tin2tin) has made this [blender addon](https://github.com/tin2tin/import_subtitles). Check it out.

## Usage from script

Import stuff

```python
import os

# SRT File
from srtranslator import SrtFile
# ASS File
from srtranslator import AssFile

from srtranslator.translators.deepl_api import DeeplApi
from srtranslator.translators.deepl_scrap import DeeplTranslator
from srtranslator.translators.translatepy import TranslatePy
from srtranslator.translators.pydeeplx import PyDeepLX
```

Initialize translator. It can be any translator, even your own, check the docs, there are instructions per translator and how to create your own.

```python
# DeepL API with quality-optimized model (recommended for complex languages like Finnish)
translator = DeeplApi(
    api_key="your-api-key",
    model_type="quality_optimized",  # Uses next-gen model for better morphology
    preserve_formatting=True,        # Keeps punctuation and casing
    tag_handling="xml",              # Protects markup from corruption
)

# Or use other translators
# translator = DeeplTranslator()  # Web scraping (no API key needed)
# translator = TranslatePy()      # Multiple backends
# translator = PyDeepLX()         # DeepLX wrapper
```

Load, translate and save. For multiple recursive files in folder, check `examples folder`

```python
filepath = "./filepath/to/srt"

# SRT File
sub = SrtFile(filepath)
# ASS File
sub = AssFile(filepath)

# Translate
sub.translate(translator, "en", "fi")

# Post-process with CPS-aware wrapping and validation (recommended for Finnish)
result = sub.postprocess(
    target_language="fi",
    use_cps_wrapping=True,   # Calculate line wrap based on subtitle duration
    target_cps=17.0,         # 17 chars/sec is comfortable for Finnish
    max_lines=2,
    validate_output=True,    # Check for CPS violations
    check_formality=True,    # Detect mixed sinä/te within scenes
)

# Print any quality warnings
if result["warnings"]:
    sub.print_warnings(target_language="fi")

# Save
sub.save(f"{os.path.splitext(filepath)[0]}_fi.srt")

# Optional: Run external post-processor
fixer_result = sub.run_external_fixer(
    f"{os.path.splitext(filepath)[0]}_fi.srt",
    command="fix-finnish-subs",
)
```

Quit translator

```python
translator.quit()
```

## Usage command line

Supported platforms: Linux and macOS.

```bash
# Basic translation
srtranslator ./filepath/to/srt -i en -o fi

# With CPS-based wrapping and validation (recommended for Finnish)
srtranslator ./file.srt -i en -o fi --use-cps --target-cps 17 --validate

# With quality-optimized DeepL model
srtranslator ./file.srt -i en -o fi -t deepl-api --auth YOUR_KEY --model-type quality_optimized

# Disable external post-processor
srtranslator ./file.srt -i en -o fi --no-external-fixer
```

## Advanced usage

```
usage: srtranslator [-h] [-i SRC_LANG] [-o DEST_LANG] [-v] [-vv] [-s] [-w WRAP_LIMIT]
                    [--use-cps] [--target-cps TARGET_CPS] [--max-lines MAX_LINES]
                    [--validate] [--no-formality-check]
                    [-t {deepl-scrap,translatepy,deepl-api,pydeeplx}]
                    [--auth AUTH] [--proxies] [--context CONTEXT]
                    [--model-type {latency_optimized,quality_optimized,prefer_quality_optimized}]
                    [--no-external-fixer] path

Translate .srt and .ass subtitle files from the command line

positional arguments:
  path                  Subtitle file to translate

options:
  -h, --help            show this help message and exit
  -i SRC_LANG, --src-lang SRC_LANG
                        Source language. Default: auto
  -o DEST_LANG, --dest-lang DEST_LANG
                        Destination language. Default: es (Spanish)
  -v, --verbose         Increase output verbosity
  -vv, --debug          Increase output verbosity for debugging
  -s, --show-browser    Show browser window (Selenium-based translators)
  -w WRAP_LIMIT, --wrap-limit WRAP_LIMIT
                        Number of characters to wrap a line. Default: 50
  --use-cps             Use CPS-based line wrapping instead of fixed character limit
  --target-cps TARGET_CPS
                        Target characters per second for wrapping/validation. Default: 17
  --max-lines MAX_LINES
                        Maximum number of lines per subtitle. Default: 2
  --validate            Run quality validation after translation (CPS, formality checks)
  --no-formality-check  Disable formality consistency checking (Finnish sinä/te)
  -t, --translator      Built-in translator to use
  --auth AUTH           API key if needed by the translator
  --proxies             Use proxy by default for pydeeplx
  --context CONTEXT     Context for DeepL translation (deepl-api only)
  --model-type          Model type for DeepL (deepl-api only)
  --no-external-fixer   Disable running fix-finnish-subs after translation
```

## Finnish Translation Features

SRTranslator includes optimizations for translating to Finnish:

### Context-Aware Translation
- **Scene boundary detection**: Context is limited to within the current scene (2+ second gaps)
- **Raw content context**: Context is built from original text, not placeholder-mutated content
- **Chunk-aware context**: Lines within the same translation batch inform each other

### Quality Validation
- **CPS checking**: Warns when subtitles exceed target characters-per-second (default: 17)
- **Formality detection**: Detects mixed sinä/te (informal/formal) within the same scene

### DeepL API Enhancements
- `tag_handling="xml"`: Protects markup and placeholders from corruption
- `preserve_formatting=True`: Maintains punctuation and casing
- `split_sentences="nonewlines"`: Prevents unwanted sentence splitting
- `model_type="quality_optimized"`: Uses next-gen model for better morphology handling

### Debug Mode
Set `DEBUG_CONTEXT=1` to see what context is sent to DeepL:
```bash
DEBUG_CONTEXT=1 srtranslator ./file.srt -i en -o fi -t deepl-api --auth KEY
```
