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

`CLAUDE.md` is a symlink to this file.

```bash
# Install dependencies
make install
# or: uv sync --all-extras   (--all-extras is what brings in the proofread extra)

# Run any Python command
uv run python -m srtranslator ...
uv run pytest
uv run ruff check
```

## Project Overview

SRTranslator is a Python library for translating subtitle files (.srt and .ass formats) using various translation services. It provides a CLI tool and a Python API.

Two console scripts (`[project.scripts]` in `pyproject.toml`):

- `srtranslator` (`__main__:main`): the general CLI.
- `srtranslator-trans` (`trans_cli:main`): the DeepL helper with Plex-style output names
  (`<name>.<lang>.srt`). It was the unversioned script `/home/ubuntu/bin/trans` until
  2026-10-06. It maps `-s`/`-l` to DeepL codes, extracts subtitles from MKV files, runs
  directories in episode order, and calls `__main__.main()` in-process with `deepl-api`,
  `--filter-sdh --merge-fragments --wrap-limit 42` and the target's instruction preset. It
  reads the key from `DEEPL_API_KEY` only and never puts it on a command line.

### Used by the Stremio subtitles add-on

The add-on (`/home/ubuntu/stremio-subtitles-add-on`) bind-mounts `/home/ubuntu/SRTranslator`
read-only at `/opt/SRTranslator` and installs it editable on every container start, so a
`docker restart stremio-addon` picks up a change here without an image rebuild. Its DeepL
engine runs the command named by `TRANSLATE_BIN` as `<bin> -s <source> [-l <target>] <file>`.
`srtranslator-trans` is the versioned replacement for the old `trans` script and is the value
`TRANSLATE_BIN` should hold.

- The add-on installs with `--no-deps --no-build-isolation`. A new runtime dependency here
  must already be in the add-on image, or the import fails there. `chardet` and
  `subtitle-filter` are (llm-subtrans brings them in).
- Keep the `srtranslator-trans` interface stable. The add-on relies on `-s` and `-l`, the
  exit status, the output name `<name>.<lang>.srt`, and a `*.proofread.json` report in the
  output's directory (it globs for it). On failure it shows stdout and stderr to the user.

## Project Structure

```
SRTranslator/
├── srtranslator/           # Main package
│   ├── __init__.py
│   ├── __main__.py         # CLI entry point (srtranslator)
│   ├── trans_cli.py        # srtranslator-trans: Plex-style names, MKV extraction, batches
│   ├── srt_file.py         # SRT subtitle handling, request planning, context, checks
│   ├── preprocess.py       # Decoding, markup and italics, SDH filter, fragment merging
│   ├── presets.py          # DeepL custom-instruction presets (only "fi")
│   ├── ass_file.py         # ASS subtitle handling
│   ├── util.py             # Utility functions
│   ├── proofread/          # Bilingual AI proof-reading (optional extra)
│   │   ├── document.py     # ProofreadCue / ProofreadDocument, both languages per cue
│   │   ├── prompt.py       # System instruction and the bilingual transcript
│   │   ├── schema.py       # pydantic response schema (the only pydantic import)
│   │   ├── guards.py       # Per-patch safety checks, all computed in code
│   │   ├── apply.py        # Guard pipeline, dedup and the change cap
│   │   ├── engine.py       # Orchestration, cost guard, batching, report
│   │   ├── cost.py         # Token estimate and price table
│   │   ├── report.py       # <output>.proofread.json
│   │   └── backends/       # base protocol, gemini (google-genai), fake (tests)
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
DEEPL_API_KEY=... uv run srtranslator ./file.srt -i en -o fi -t deepl-api \
    --filter-sdh --merge-fragments --instruction-preset fi

# DeepL helper with Plex-style names (movie.en.srt -> movie.fi.srt)
DEEPL_API_KEY=... uv run srtranslator-trans ./movie.en.srt
uv run srtranslator ./file.srt -i en -o es -t translatepy
uv run srtranslator ./file.srt -i en -o es -t pydeeplx --proxies

# Proof-read an existing translation against its original (edits in place, keeps .bak)
uv run srtranslator ./file_fi.srt --proofread-only --source ./file.srt -i en -o fi
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
    max_items: int | None = None  # Maximum cues per request, None for no limit

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
  - `max_char = 5000`, `max_items = 50` (DeepL's documented limit; it accepted 51 in a test)
  - `glossary_id` (CLI `--glossary-id`) is left out of the request when the source is `auto`,
    because DeepL needs the language pair
  - With `tag_handling="xml"` DeepL parses every text **and the context** as XML, so
    `xml_escape_text` escapes bare `&` and `<` before sending and `xml_unescape_text` undoes
    the entities after. One stray `&` fails the whole request otherwise
  - `--auth` may be omitted: `__main__` then reads `DEEPL_API_KEY`
- `translatepy.TranslatePy`: Uses translatepy library
- `pydeeplx.PyDeepLX`: DeepLX API wrapper with proxy support


## AI proof-reading (`proofread/`)

An optional stage that reads the whole programme in both languages and corrects only cues
whose meaning came out wrong. Install with the `proofread` extra (`google-genai`, `pydantic`).

**Where it runs.** `__main__.main()` calls it after `sub.translate()` and before
`postprocess()`. At that point `sub.content` is one line per cue and `sub.raw_contents` still
holds the source text, so both languages are available and layout has not been decided yet.
The order is: translate, proof-read, wrap, save, `fix-finnish-subs` (Finnish targets only).

**How it is turned on.** Tri-state. `--proofread` forces it on and errors if it cannot run,
`--no-proofread` forces it off, and with neither it runs when `google-genai` imports and
Gemini credentials are in the environment.

**Patches are identified by cue id, never by position**, and every one must quote the text it
is replacing. That precondition is what makes the stage safe: a model that mixed up two cues
produces a patch that no longer matches and is rejected instead of applied.

### Gotchas

- **Never trust the model's arithmetic or its account of what it preserved.** Every guard in
  `guards.py` recomputes the fact itself. This is the same lesson as sisusub's
  `_shortening_preserves_structure`, whose negation word list is reused here.
- **`////` is the dialogue line break inside the pipeline.** `document.to_display` turns it
  into a real newline for the prompt and `target_to_internal` puts it back, so `wrap_lines()`
  behaves exactly as it does without the stage. Get this wrong and dash dialogue collapses.
  The model never sees the placeholder, so `check_sanity` rejects one arriving in a patch:
  `wrap_lines()` would otherwise turn it into a speaker line no guard had inspected.
- **`document.DIALOGUE_DASHES` is the single definition of what opens a speaker turn**, and
  `guards` imports it. They disagreed once: `is_dialogue_text` matched only the ASCII hyphen
  while the guards accepted en and em dashes. A cue whose hyphens DeepL returned as en dashes
  was then treated as narration, and its correction was flattened onto one line, silently
  merging two speakers. If you touch one, touch both.
- **Guards must validate the exact string that will be written.** `apply.decide` canonicalises
  `after` through `guards.canonical` *before* any check runs. Validating the raw model string
  and writing a tidied one let a blank line survive as a third speaker line.
- **Whole-cue booleans are not enough for a multi-speaker cue.** `check_negation` compares line
  by line when the line count is unchanged. A single presence check for the cue let one
  speaker'"'"'s negation be removed while another'"'"'s kept the cue looking negative.
- **The model never sees tags.** `document.to_display` strips them, because the guards reject
  any correction containing markup. `ProofreadCue.italics` remembers `none`, `all` or
  `partial`: `apply_italics` wraps a corrected `all` cue in `<i>` again, and
  `guards.check_italics` rejects any patch to a `partial` cue (`italic_markup`), since the
  correction cannot say which words were italic.
- **Flagged cues reach the model as `CHECK:` lines.** `SrtFile.attention` (`empty`,
  `untranslated`, `dialogue_lines`) is copied into `ProofreadDocument.attention` and printed
  under the cue. That changed the transcript format, so `PROMPT_FORMAT_VERSION` is `2`. Bump
  it again whenever the transcript changes.
- **A dash with nothing after it is not an utterance.** `check_structure` rejects it; the line
  count and the dash both survive such a patch, so nothing else catches it.
- **Pair mode does no wrapping afterwards.** `_render_for_file` therefore keeps whatever line
  breaks a correction came back with, and only wraps a single line that is too long, at the
  width the file already uses. Flattening there destroyed a correctly wrapped cue.
- **The change cap has a floor of three patches** (`apply.MIN_PATCHES_ALLOWED`). Without it a
  short file could never be corrected, because one patch in five cues is already 20%.
- **Evidence for a number change need not contain a digit.** The original often spells the
  number out ("half past five"), so only non-empty evidence and a meaning category are
  required.
- **A failure in this stage never raises into `main()`'s backup path.** The translation has
  already been paid for, and `main()`'s handler truncates the file to a `.tmp` backup.
  `run_proofread` catches everything and returns `status="error"`, but that is not the whole
  boundary: `run_pipeline_proofread` and `run_proofread_only` catch bare `Exception` too,
  because report writing raises `OSError` and `genai.Client` raises untyped auth errors, and
  neither is inside `run_proofread`. Keep those catches broad.
- **The report is written with mode `w`, so its path is checked against the subtitles first.**
  `engine._report_path` refuses a path that resolves to the input, the source, the output or
  the `.bak`, and it runs before the model is called. Without it `--proofread-report` aimed at
  a subtitle replaced that subtitle with JSON, during a dry run, with no backup.
- **Matching cue counts do not mean the cues correspond.** `_check_timeline_alignment` refuses
  a pair whose per-cue offsets spread by more than `MAX_OFFSET_SPREAD_SECONDS`. A uniform
  shift passes, because ffsubsync legitimately produces one. Patch preconditions cannot catch
  a misalignment: they quote the target text, which matches perfectly while the source beside
  it is the wrong cue.
- **A model answer with no `patches` key is a failed call, not a clean review.** `_decode`
  raises rather than defaulting to an empty list, which used to report a quota error as a
  subtitle that needed no corrections.
- **`thinking_level`, never `thinking_budget`.** The Gemini 3 models reject the budget form,
  and sending both is an error. The SDK normalises the level to its own enum, so compare
  `.value` in tests.
- **Prices in `cost.py` were verified in September 2026 and double on 1 January 2027.** An
  unknown model yields a `None` cost, which never trips the cost guard.

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
  target-language text below that index. `_load_backup` has the matching half of this: it
  restores `raw_contents` after loading the `.tmp` file, which otherwise overwrites the
  source text of every resumed cue with that cue's own translation.
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
- **`SrtFile` and `AssFile` no longer share their chunking and context logic.** `SrtFile`
  plans requests with `_plan_chunks` (30 s scenes, split at the longest pause) and sends plain
  source lines before, inside and after the request as context. `AssFile` kept the older
  scheme: 2.0 s scenes, `_get_next_chunk`, context limited to the scene with `Scene N` /
  `Previous dialogue:` headings. Decoding, empty-cue removal, italics, `--filter-sdh`,
  `--merge-fragments` and the post-request checks exist only in `SrtFile`. `SrtFile` keeps a
  `raw_contents` map for clean context; `AssFile` uses `util.clean_context_line` instead.
- **Two scene gaps, on purpose.** `srt_file.SCENE_GAP_SECONDS` (30 s) plans DeepL requests.
  `proofread/document.SCENE_GAP_SECONDS` (2.0 s) only breaks up the reviewer's transcript.
  Do not unify them.
- **A backup keeps its empty cues.** `load_from_file` passes `drop_empty=False` for the `.tmp`
  file: a backup holds one translation per source cue, and dropping an empty one would shift
  every later cue onto the wrong source.
- **A wrong cue count raises, it never zips.** `translate()` raises when the translator
  returns a different number of cues than it was sent. Pairing them anyway would put every
  later translation on the wrong cue; raising lets `main()` save the `.tmp` backup.
- **`srtranslator-trans` deletes a leftover `.tmp` before a run.** A backup from a failed run
  of an older pipeline (different filtering or merging) has different cue numbering, so
  resuming from it would mispair cues.
- **Only `deepl-api` keeps `<i>`.** `main()` sets `keep_italics` for it alone, because only
  DeepL's XML tag handling carries tags through. `preprocess.join_italic_spans` must run
  first: with one italic span per line, DeepL scattered the tags across the Finnish word order
  and dropped the words between them.
- **`--filter-sdh` does not use all of subtitle-filter.** Its font rule deleted the text
  inside `<font>`, its speaker rule deleted any capitalised phrase before a colon
  ("The plan is simple:"), and its greedy sound-effect and music rules deleted the dialogue
  between two effects or two ♪ spans. `preprocess.filter_sdh` calls the other per-cue rules
  itself and replaces those four. Its regexes read `/` and `#` as annotation markers, so in-word slashes,
  `#<digit>` and italic tags are swapped for private-use characters while it runs.
- **`load_subtitle` tries ASS first** and falls back to SRT, so every run prints a
  "Loading as ASS" line even for SRT. That is not an error.
