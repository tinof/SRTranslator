# SRTranslator

> CLI-only subtitle translator for Linux and macOS.

This is a fork of [sinedie/SRTranslator](https://github.com/sinedie/SRTranslator) with enhanced context-aware translation features and modernized build tooling.

## Install

```bash
# Using uv (recommended)
uv tool install git+https://github.com/tinof/SRTranslator.git

# With AI proof-reading (adds google-genai and pydantic)
uv tool install "srtranslator[proofread] @ git+https://github.com/tinof/SRTranslator.git"

# Upgrade to latest version
uv tool upgrade srtranslator
```

**From PyPI (original package, not this fork):**
```bash
uv tool install srtranslator
```

## Usage from script

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

Initialize translator:

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

Load, translate and save:

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

# Cleanup
translator.quit()
```

## Command line usage

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

### Full options

```
usage: srtranslator [-h] [-i SRC_LANG] [-o DEST_LANG] [-v] [-vv] [-s] [-w WRAP_LIMIT]
                    [--use-cps] [--target-cps TARGET_CPS] [--max-lines MAX_LINES] [--validate]
                    [--no-formality-check] [-t {deepl-scrap,translatepy,deepl-api,pydeeplx}]
                    [--auth AUTH] [--proxies] [--context CONTEXT]
                    [--model-type {quality_optimized,latency_optimized,prefer_quality_optimized}]
                    [--instruction TEXT] [--no-external-fixer] [--proofread] [--no-proofread]
                    [--proofread-only] [--source PATH] [--proofread-model NAME]
                    [--proofread-thinking {low,medium,high}]
                    [--proofread-min-severity {minor,major,critical}]
                    [--proofread-max-change FRACTION] [--proofread-max-cost USD]
                    [--proofread-report PATH] [--proofread-dry-run]
                    path

Translate .srt and .ass subtitle files from the command line

positional arguments:
  path                  Subtitle file to translate

options:
  -h, --help            show this help message and exit
  -i, --src-lang SRC_LANG
                        Source language. Default: auto
  -o, --dest-lang DEST_LANG
                        Destination language. Default: es (Spanish)
  -v, --verbose         Increase output verbosity
  -vv, --debug          Increase output verbosity for debugging
  -s, --show-browser    Show browser window (Selenium-based translators)
  -w, --wrap-limit WRAP_LIMIT
                        Number of characters -including spaces- to wrap a line of text.
                        Default: 50
  --use-cps             Use CPS-based line wrapping instead of fixed character limit
  --target-cps TARGET_CPS
                        Target characters per second for CPS-based wrapping and validation.
                        Default: 17
  --max-lines MAX_LINES
                        Maximum number of lines per subtitle. Default: 2
  --validate            Run quality validation after translation (CPS, formality checks)
  --no-formality-check  Disable formality consistency checking (Finnish sinä/te)
  -t, --translator {deepl-scrap,translatepy,deepl-api,pydeeplx}
                        Built-in translator to use
  --auth AUTH           API key if needed by the translator
  --proxies             Use proxy by default for pydeeplx
  --context CONTEXT     Context for DeepL translation (only for deepl-api)
  --model-type {quality_optimized,latency_optimized,prefer_quality_optimized}
                        DeepL model type (only for deepl-api). quality_optimized is the next-
                        generation model and the default. latency_optimized is the faster
                        classic model. prefer_quality_optimized is a legacy alias of
                        quality_optimized. Default: quality_optimized
  --instruction TEXT    DeepL custom instruction, repeatable (only for deepl-api). At most 10
                        instructions of 300 characters each, for example 'Keep character names
                        untranslated'
  --no-external-fixer   Disable running fix-finnish-subs after translation

AI proof-reading:
  Review the finished translation against the original with a Gemini model, and correct only
  cues whose meaning came out wrong. Runs automatically when google-genai is installed and
  Gemini credentials are set.

  --proofread           Force proof-reading on, and fail loudly if it cannot run
  --no-proofread        Skip proof-reading even when credentials are available
  --proofread-only      Proof-read an already translated file instead of translating. The
                        positional path is the translated subtitle, --source is the original.
                        The file is edited in place and the previous version is kept as .bak
  --source PATH         Original subtitle file, required by --proofread-only
  --proofread-model NAME
                        Reviewing model. Default: $SRTRANSLATOR_PROOFREAD_MODEL or
                        gemini-3.8-flash
  --proofread-thinking {low,medium,high}
                        Reasoning level of the reviewing model. Default:
                        $GEMINI_THINKING_LEVEL or medium
  --proofread-min-severity {minor,major,critical}
                        Ignore corrections below this severity. Default: minor
  --proofread-max-change FRACTION
                        Refuse the whole review if it wants to change more than this share of
                        the cues. Default: 0.30
  --proofread-max-cost USD
                        Skip the review if it is estimated to cost more than this. 0 disables.
                        Default: 0.50
  --proofread-report PATH
                        Where to write the review report. Default: <output>.proofread.json
  --proofread-dry-run   Review and write the report, but do not change the subtitles
```

## Finnish translation features

SRTranslator includes optimizations for translating to Finnish:

### Context-aware translation
- **Scene boundary detection**: Context is limited to within the current scene (2+ second gaps)
- **Raw content context**: Context is built from original text, not placeholder-mutated content
- **Chunk-aware context**: Lines within the same translation batch inform each other

### Quality validation
- **CPS checking**: Warns when subtitles exceed target characters-per-second (default: 17)
- **Formality detection**: Detects mixed sinä/te (informal/formal) within the same scene

### DeepL API enhancements
- `tag_handling="xml"`: Protects markup and placeholders from corruption
- `preserve_formatting=True`: Maintains punctuation and casing
- `split_sentences="nonewlines"`: Prevents unwanted sentence splitting
- `model_type="quality_optimized"`: Uses next-gen model for better morphology handling

### Debug mode
Set `DEBUG_CONTEXT=1` to see what context is sent to DeepL:
```bash
DEBUG_CONTEXT=1 srtranslator ./file.srt -i en -o fi -t deepl-api --auth KEY
```

## AI proof-reading

DeepL translates a few lines at a time. It cannot tell which sense of an ambiguous word a
scene calls for, whether an idiom should be carried across, or whether two characters have
been on formal terms all along. The proof-reading stage reads the whole programme in both
languages in one pass and corrects only the cues whose meaning came out wrong.

### Setup

Install the `proofread` extra, then point the stage at Gemini. Vertex AI with application
default credentials is used when `GEMINI_USE_VERTEX` is set, otherwise an API key.

```bash
# Vertex AI
export GEMINI_USE_VERTEX=1
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_CLOUD_LOCATION=global   # optional, this is the default

# or the Gemini Developer API
export GEMINI_API_KEY=...

# optional
export SRTRANSLATOR_PROOFREAD_MODEL=gemini-3.8-flash
export GEMINI_THINKING_LEVEL=medium
```

With the extra installed and credentials set, proof-reading runs automatically after every
translation. Use `--no-proofread` to skip it.

### Proof-reading an existing translation

```bash
srtranslator movie_fi.srt --proofread-only --source movie.srt -i en -o fi
```

The file is edited in place and the previous version is kept as `movie_fi.srt.bak`. Add
`--proofread-dry-run` to write the report without touching the subtitles.

### What it will and will not change

It reports only meaning: mistranslations, the wrong sense of an ambiguous word, omissions and
invented content, literal idioms, inconsistent sinä/te address forms, names and terms that
drift between cues, and errors of person, gender, number or tense. Line length, reading speed,
punctuation and spelling are left to `fix-finnish-subs`, which runs afterwards.

Every correction is then checked in code before it is applied. A correction is thrown away
when it does not quote the cue it claims to be fixing, changes the number of speaker lines or
drops a dialogue dash, alters a number or a negation without evidence from the original, or
grows so long that the cue can no longer be read in the time it is on screen. If a review
wants to change more than 30% of the cues it is refused whole, because a review that large is
rewriting the style rather than fixing errors.

### Reports

Every run writes `<output>.proofread.json` next to the subtitle: the model and prompt digest,
the token usage and cost, every applied correction with its category, severity, evidence and
reason, and every rejected one with the check that rejected it.

### Cost

A 45-minute episode is roughly 20,000 to 25,000 bilingual input tokens in one call. On
`gemini-3.8-flash` at the September 2026 rates that is about $0.03 to $0.06 per episode.
`--proofread-max-cost` (default $0.50) skips the review rather than overspend on an unexpectedly
large file. Only a file too large for one call is split into scene-aligned batches, which share
one cached copy of the transcript.

### Order of the pipeline

```
translate -> proof-read (meaning) -> wrap lines -> save -> fix-finnish-subs (mechanics)
```

Meaning is corrected before layout, because the mechanical fixer shortens and reflows cues to
fit reading speed and must work on the final text. `--proofread-only` does not run the fixer:
that chain is not idempotent and must run exactly once per file.

## Development

This project uses **uv** as the package manager.

```bash
# Clone the repository
git clone https://github.com/tinof/SRTranslator.git
cd SRTranslator

# Install dependencies
make install

# Run checks (linting + type checking)
make check

# Run tests
make test

# Format code
make fmt

# Build package
make build
```

See [AGENTS.md](AGENTS.md) for more development details.

## Blender integration

[tin2tin](https://github.com/tin2tin) has made this [blender addon](https://github.com/tin2tin/import_subtitles). Check it out.

## License

Free for non-commercial use.
