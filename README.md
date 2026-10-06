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
# SRT File with input cleaning; keep_italics only with DeeplApi (XML tag handling)
sub = SrtFile(filepath, keep_italics=True, filter_sdh=True, merge_fragments=True)
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

# The full Finnish pipeline. deepl-api reads DEEPL_API_KEY when --auth is omitted,
# which keeps the key out of the process list
export DEEPL_API_KEY=...
srtranslator ./file.srt -i en -o fi -t deepl-api --filter-sdh --merge-fragments \
    --instruction-preset fi --wrap-limit 42 --output ./file.fi.srt

# Disable external post-processor
srtranslator ./file.srt -i en -o fi --no-external-fixer
```

Without `--output` the translation is written to `<input>_<dest-lang>.<ext>`.

`--instruction-preset fi` adds 8 built-in DeepL custom instructions for Finnish subtitles. They
are placed before any `--instruction`, and the total is still limited to 10. `fi` is the only
preset. `--glossary-id` applies a DeepL glossary; it is ignored when the source language is
`auto`, because a glossary belongs to a language pair.

`fix-finnish-subs` runs after saving only when the target language is Finnish. It is called
with `--no-ai-review --width-limit 42 --max-cps 17 --cps-target 15` and writes its report to
`<output>.fixer-report.txt`. Install [sisusub](https://github.com/tinof/sisusub) to get it;
without it the step is skipped with a warning.

### Full options

```
usage: srtranslator [-h] [-i SRC_LANG] [-o DEST_LANG] [-v] [-vv] [-s] [-w WRAP_LIMIT] [--use-cps]
                    [--target-cps TARGET_CPS] [--max-lines MAX_LINES] [--validate]
                    [--no-formality-check] [-t {deepl-scrap,translatepy,deepl-api,pydeeplx}]
                    [--auth AUTH] [--output PATH] [--filter-sdh] [--merge-fragments] [--proxies]
                    [--context CONTEXT]
                    [--model-type {quality_optimized,latency_optimized,prefer_quality_optimized}]
                    [--instruction TEXT] [--instruction-preset LANG] [--glossary-id ID]
                    [--no-external-fixer] [--proofread] [--no-proofread] [--proofread-only]
                    [--source PATH] [--proofread-model NAME]
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
                        Number of characters -including spaces- to wrap a line of text. Default:
                        50
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
  --auth AUTH           API key if needed by the translator. deepl-api reads $DEEPL_API_KEY when
                        this is omitted, which keeps the key out of the process list
  --output PATH         Where to write the translation. Default: <input>_<dest-lang>.<ext>
  --filter-sdh          Remove hearing-impaired annotations (sound effects, music, speaker labels)
                        before translating. .srt only
  --merge-fragments     Join a sentence split across two short cues before translating. .srt only
  --proxies             Use proxy by default for pydeeplx
  --context CONTEXT     Context for DeepL translation (only for deepl-api)
  --model-type {quality_optimized,latency_optimized,prefer_quality_optimized}
                        DeepL model type (only for deepl-api). quality_optimized is the next-
                        generation model and the default. latency_optimized is the faster classic
                        model. prefer_quality_optimized is a legacy alias of quality_optimized.
                        Default: quality_optimized
  --instruction TEXT    DeepL custom instruction, repeatable (only for deepl-api). At most 10
                        instructions of 300 characters each, for example 'Keep character names
                        untranslated'
  --instruction-preset LANG
                        Add a built-in set of custom instructions for this target language (only
                        for deepl-api). Available: fi
  --glossary-id ID      DeepL glossary to apply (only for deepl-api). Ignored when the source
                        language is auto, because DeepL needs the language pair
  --no-external-fixer   Disable running fix-finnish-subs after translation

AI proof-reading:
  Review the finished translation against the original with a Gemini model, and correct only
  cues whose meaning came out wrong. Runs automatically when google-genai is installed and
  Gemini credentials are set.

  --proofread           Force proof-reading on, and fail loudly if it cannot run
  --no-proofread        Skip proof-reading even when credentials are available
  --proofread-only      Proof-read an already translated file instead of translating. The
                        positional path is the translated subtitle, --source is the original. The
                        file is edited in place and the previous version is kept as .bak
  --source PATH         Original subtitle file, required by --proofread-only
  --proofread-model NAME
                        Reviewing model. Default: $SRTRANSLATOR_PROOFREAD_MODEL or
                        gemini-3.8-flash
  --proofread-thinking {low,medium,high}
                        Reasoning level of the reviewing model. Default: $GEMINI_THINKING_LEVEL or
                        medium
  --proofread-min-severity {minor,major,critical}
                        Ignore corrections below this severity. Default: minor
  --proofread-max-change FRACTION
                        Refuse the whole review if it wants to change more than this share of the
                        cues. Default: 0.30
  --proofread-max-cost USD
                        Skip the review if it is estimated to cost more than this. 0 disables.
                        Default: 0.50
  --proofread-report PATH
                        Where to write the review report. Default: <output>.proofread.json
  --proofread-dry-run   Review and write the report, but do not change the subtitles
```

## srtranslator-trans

`srtranslator-trans` is a DeepL helper with Plex-style output names. It replaces the
unversioned `trans` script, and the Stremio subtitles add-on can run it as its
`TRANSLATE_BIN`.

```bash
export DEEPL_API_KEY=...
srtranslator-trans movie.en.srt            # writes movie.fi.srt
srtranslator-trans -s sv -l German show.S01E02.mkv
srtranslator-trans                         # every .srt here without a language suffix
```

- **Output** is `<name>.<lang>.srt`. Language suffixes such as `.en` are removed from the
  input name first.
- **`-l`** is the target, by code or English name (default Finnish). **`-s`** is the source
  (default `en`). The source is checked against DeepL's list of source languages: `no` and
  `nn` become `nb`, and an unknown one becomes `auto` so DeepL detects it.
- **MKV input**: an existing `<name>.en.srt` is used if there is one. Otherwise the English
  text subtitle track is extracted with ffmpeg, or the first text track when there is no
  English one. When the file has only bitmap tracks, English subtitles are downloaded with
  `psubs`.
- **Batch mode**: with no file, it translates every `.srt` in the current directory whose name
  does not end in a two-letter language suffix such as `.en.srt`, in S##E## order, or the
  `.mkv` files when there are none. A file whose
  output already exists is skipped.
- **Pipeline**: it runs `srtranslator` in-process with `deepl-api`, `quality_optimized`,
  `--filter-sdh --merge-fragments --wrap-limit 42`, and the instruction preset of the target
  language when one exists. Proof-reading and `fix-finnish-subs` follow as usual.
- **Key**: it reads `DEEPL_API_KEY` and never puts the key on a command line.
- **Leftover backup**: a `.tmp` backup from an earlier failed run is removed before the run,
  because it may come from a different version of the pipeline.
- **`--debug`** prints the context sent to DeepL for each request.

## Finnish translation features

SRTranslator includes optimizations for translating to Finnish:

The features below apply to `.srt` files. `.ass` files keep the earlier scheme (2-second
scenes, context limited to the scene) and none of the input steps, italics handling or checks.

### Reading the input
- **Encoding**: the file is decoded as UTF-16 (with a BOM) or UTF-8 (with or without a BOM).
  A UTF-8 file with a few broken bytes loses only those bytes. A multi-byte encoding chardet
  is at least 90% sure of comes next. Otherwise cp1252, cp1250 and cp1251 are each tried, and
  the one that produces the fewest implausible characters wins. Accented letters of a cp1252
  file are no longer dropped.
- **Empty cues**: a cue with no readable text is removed and the rest are renumbered. It is
  no longer sent as `...`, which put an empty subtitle on screen.
- **`--filter-sdh`**: removes hearing-impaired annotations (sound effects, music, credits,
  asterisks, lone dashes) with the rules of the
  [subtitle-filter](https://pypi.org/project/subtitle-filter/) package. Three of its rules lose
  text and are replaced: its font rule deleted the words inside `<font>` (now only the tag
  goes); its speaker rule deleted any capitalised phrase before a colon (now only an
  all-capitals label such as `JOHN:` or `MAN #2:` goes, never `OK:` or `TV:`, and two labelled
  lines become dash dialogue); and its greedy sound-effect and music rules deleted the
  dialogue between two effects or two ♪ spans (`[door slams] I'm here. [gunshot]` now keeps
  `I'm here.`, and `♪ song ♪ Wait! ♪ song ♪` keeps `Wait!`). Slashes inside a word (`and/or`, `24/7`), `#` before a digit (`#1 fan`) and
  italics are protected from its patterns. A cue left with no text is removed.
- **`--merge-fragments`**: joins a sentence that the source split across two short cues, so
  DeepL translates it whole. Ported from llm-subtrans. Two cues merge only when one of them
  lasts 1.5 s or less, the gap is 0.3 s or less, the first does not end a sentence, neither
  is dash dialogue, and the result lasts 6 s or less, has 84 characters or less and reads at
  17 characters per second or less. The merged cue is not split again after translation.

### Italics
- With `deepl-api`, `<i>` tags are kept and travel through DeepL's XML tag handling. Other
  tags (`<font>`, `<b>`, ASS overrides such as `{\an8}`) are removed, but their text stays.
  With any other translator all tags are removed.
- Italic lines that follow each other are joined into one span first. Two spans in one cue
  made DeepL move the tags around the Finnish word order and drop the words between them.

### Context-aware translation
- **Scenes**: a silence of 30 s or more (`SCENE_GAP_SECONDS`) starts a new scene.
- **Requests follow the scenes**: whole scenes are packed into one request while they fit.
  A scene too large for one request is split at its longest pause. A DeepL request holds up
  to 5000 characters and 50 cues.
- **Context in reading order**: each request carries the source text before it (up to 4000
  characters), its own lines, and the text after it (up to 2000 characters). Context may
  cross a scene boundary, because names and topics carry over. Context is not billed.
- **Raw content context**: context is built from the original text, never from a translation.
  On a resumed run nothing before the resume point is used.

### Checks after each request
- A translator answer with the wrong number of cues stops the run. The `.tmp` backup keeps
  the cues translated so far.
- A cue that comes back empty, or unchanged from the source when the source has 15 or more
  letters, is sent again on its own. If it is still wrong, it is flagged for the proof-reader.
- A stray `////` dialogue placeholder in a cue that is not dialogue is removed. A dialogue cue
  whose number of speaker lines changed is flagged for the proof-reader.
- Cues faster than 25 characters per second are counted in the log. Shortening them is left
  to `fix-finnish-subs`.

### Finnish instruction preset
`--instruction-preset fi` asks DeepL for concise subtitles without filler words, `sinä` for
one person and `te` only for a group or a clearly formal situation, idiomatic Finnish, the
original tone, profanity of the same strength, unchanged names, no added punctuation, and
short common words. Tested on the live API on 2026-10-06: DeepL accepts instructions for
Finnish and follows them. On 15 test lines the output was 20% shorter, filler words were
gone, and sinä/te still matched the speakers. An earlier rule, "keep the profanity", made
DeepL swear harder than the source, so the rule now asks for the same strength.

On a 250-cue sample of a real film (2026-10-06), the current pipeline compared with the
previous one: italics kept in 22 cues instead of 0, 6% fewer characters, 19.8% of cues over
17 characters per second instead of 22.3%, and 12.8% over 20 instead of 16.0%.

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

The model never sees markup. A cue that is italic as a whole gets its italics back around the
corrected text. A cue that is italic only in part is never rewritten (rejection reason
`italic_markup`), because the correction cannot say which words were italic.

Cues that the translation step flagged (empty, unchanged from the source, or with a changed
number of speaker lines) carry a `CHECK:` line in the transcript, and the model is told to look
at those first.

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
decode -> filter SDH -> merge fragments -> translate -> proof-read (meaning) -> wrap lines
       -> save -> fix-finnish-subs (mechanics, Finnish only)
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
