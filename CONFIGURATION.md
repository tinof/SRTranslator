# SRTranslator Configuration Guide

## Context, Scenes and Requests

This section describes `.srt` files (`SrtFile`). `.ass` files still use the earlier scheme,
see [ASS files](#ass-files) below.

### Default Values

```python
# srtranslator/srt_file.py
SCENE_GAP_SECONDS = 30.0       # A silence this long starts a new scene
CONTEXT_CHARS_BEFORE = 4000    # Source text before the request
CONTEXT_CHARS_AFTER = 2000     # Source text after the request

# srtranslator/translators/deepl_api.py (class DeeplApi)
max_char = 5000                # Characters per request
max_items = 50                 # Cues per request, DeepL's documented limit
```

These are module constants and class attributes, not CLI options. `_build_deepl_context()`
also takes `max_chars_before` and `max_chars_after` as arguments.

### Scenes

A gap of 30 s or more between two cues starts a new scene. A silence that long reads as a cut
to the viewer. Scenes decide where requests begin and end. They do not limit the context.
`validate()` uses the same scenes for its mixed sinä/te check.

### Requests

`_plan_chunks()` splits the untranslated cues into requests. It is ported from llm-subtrans
`SubtitleBatcher`:

1. A scene that fits in one request stays whole.
2. A scene too large for one request is split at its longest pause, and each part again,
   until every part fits. A request boundary therefore falls where the conversation pauses
   most.
3. Consecutive scenes and parts are packed into one request while the result still fits.

A request fits when its text, plus one character per cue, is under `max_char` and it has no
more than `max_items` cues. `base.Translator` sets `max_items = None`, so the other
translators are limited by characters only.

### Context

DeepL translates each cue of a request on its own, so the context is the only place a cue
can see its neighbours. Each request gets, in reading order:

1. the source text before the request, up to 4000 characters
2. the request's own lines
3. the source text after the request, up to 2000 characters

The context is one line per cue: plain source text, with no tags, line numbers or headings.
It may cross a scene boundary, because names and topics carry over. On a resumed run, lines
before the resume point are never used, because they hold translations, not source text. A
global `--context` is placed before this context in the same field.

Context is not billed. The hard limit is DeepL's 128 KiB request body: `util.fit_context`
trims the start of the context to keep the request under 120,000 bytes. With the current
budgets it never has to.

### When to Adjust

- **More context**: raise `CONTEXT_CHARS_BEFORE` or `CONTEXT_CHARS_AFTER`. Context is free,
  so the only cost is the size of the request.
- **Request boundaries**: lower `SCENE_GAP_SECONDS` to make requests break at shorter pauses.
  This does not change what the context contains.
- **Larger requests**: there is nothing to gain. DeepL bills the text, not the requests, and
  50 cues is its documented limit.

### ASS files

`AssFile` keeps the earlier scheme. Scenes start at 2.0 s gaps. Requests are filled up to
`max_char` by `_get_next_chunk()` without regard to scenes. The context stays inside the
current scene and is formatted as `Scene N`, `Earlier in this scene:` (lines cut to 50
characters, up to 2000 characters), `Previous dialogue:` (up to 2000 characters) and
`Upcoming dialogue:` (up to 1000 characters), with line numbers. A change to `SrtFile` does
not reach `AssFile`.

## DeepL API Settings

### Model Selection

**Quality-optimized (recommended for EN→FI):**
```bash
--model-type quality_optimized
```
- Uses next-gen DeepL models
- Best for Finnish translation
- Available on Free tier

**Latency-optimized (for speed):**
```bash
--model-type latency_optimized
```
- Uses classic models
- Faster processing
- Good for testing

**Legacy alias:**
```bash
--model-type prefer_quality_optimized
```
- Same as `quality_optimized`

### API Key

`deepl-api` reads `DEEPL_API_KEY` when `--auth` is omitted. This keeps the key out of the
process list.

### Custom Instructions

`--instruction TEXT` adds a DeepL custom instruction and can be repeated.
`--instruction-preset fi` adds the 8 built-in Finnish instructions from
`srtranslator/presets.py`, placed before any `--instruction`. DeepL accepts at most 10
instructions of 300 characters each, preset included. `fi` is the only preset.

### Glossary

`--glossary-id ID` applies a DeepL glossary. A glossary belongs to a language pair, so it is
ignored when the source language is `auto`. Pass `-i` to use one.

### Global Context Examples

**TV Series:**
```bash
--context "Television drama series. Natural conversational dialogue."
```

**Documentary:**
```bash
--context "Educational documentary. Clear and informative narration."
```

**Action Movie:**
```bash
--context "Action thriller film. Dynamic and intense dialogue."
```

**Period Drama:**
```bash
--context "Historical drama set in 1920s. Formal period-appropriate language."
```

## Input Cleaning (.srt)

These steps run when the file is loaded, before any request is planned.

| Step | When | What it does |
|---|---|---|
| Decoding | always | UTF-16 with a BOM, UTF-8 (with or without a BOM; a few broken bytes are dropped), a multi-byte encoding chardet is 90% sure of, then whichever of cp1252, cp1250 and cp1251 yields the fewest implausible characters |
| Empty cues | always | A cue with no readable text is removed and the rest are renumbered |
| Markup | always | Font, colour and other tags and ASS overrides are removed, their text kept. `<i>` is kept only with `deepl-api`, and adjacent italic spans are joined into one |
| Hearing-impaired filter | `--filter-sdh` | subtitle-filter's rules for asterisks, music, credits, comma spacing and lone dashes. Its font, speaker and greedy sound-effect rules are replaced with ones that keep dialogue, and in-word slashes, `#` before a digit and italics are protected from it |
| Fragment merging | `--merge-fragments` | Joins two cues that are halves of one sentence |

The limits for fragment merging are in `srtranslator/preprocess.py`, ported from llm-subtrans:

```python
MERGE_MAX_FRAGMENT_SECONDS = 1.5  # One of the two cues must be this short
MERGE_MAX_GAP_SECONDS = 0.3       # Gap between them
MERGE_MAX_TOTAL_SECONDS = 6.0     # Length of the merged cue
MERGE_MAX_CHARS = 84              # Characters in the merged cue
MERGE_MAX_CPS = 17.0              # Reading speed of the merged cue
```

The first cue must not end a sentence, and neither cue may be dash dialogue.

## Checks After Each Request (.srt)

| Problem | What happens |
|---|---|
| Wrong number of cues in the answer | The run stops with an error. The `.tmp` backup keeps the cues translated so far |
| Empty cue | Sent again on its own. Still empty: flagged `empty` |
| Cue identical to the source, source has 15 or more letters | Sent again on its own. Still identical: flagged `untranslated` |
| `////` placeholder in a cue that is not dialogue | Removed |
| Dialogue cue with a changed number of speaker lines | Flagged `dialogue_lines` |
| Cue faster than 25 characters per second | Counted in the log only |

Flagged cues are kept in `SrtFile.attention` and shown to the proof-reader as `CHECK:` lines.

## AI Proof-Reading Settings

The proof-reading stage is a second pass that reads the whole programme in both languages and
corrects cues whose meaning came out wrong. It is separate from the DeepL context settings
above: context improves the translation as it is made, proof-reading catches what context
could not prevent.

### Turning it on

Install the extra and set Gemini credentials. It then runs after every translation.

```bash
uv tool install "srtranslator[proofread] @ git+https://github.com/tinof/SRTranslator.git"

export GEMINI_USE_VERTEX=1
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_CLOUD_LOCATION=global     # optional, the default
# or, instead of Vertex:
export GEMINI_API_KEY=...
```

| Variable | Effect |
|---|---|
| `GEMINI_USE_VERTEX` | Use Vertex AI with application default credentials |
| `GOOGLE_CLOUD_PROJECT` | Vertex project, required when using Vertex |
| `GOOGLE_CLOUD_LOCATION` | Vertex location. Default: `global` |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini Developer API key, used when Vertex is off |
| `SRTRANSLATOR_PROOFREAD_MODEL` | Reviewing model. Default: `gemini-3.8-flash` |
| `GEMINI_THINKING_LEVEL` | `low`, `medium` or `high`. Default: `medium` |

### Defaults and when to change them

```python
model                 = "gemini-3.8-flash"  # --proofread-model
thinking_level        = "medium"            # --proofread-thinking
min_severity          = "minor"             # --proofread-min-severity
max_change_fraction   = 0.30                # --proofread-max-change
max_cost_usd          = 0.50                # --proofread-max-cost
```

**Thinking level.** `medium` is the default because choosing the right sense of an ambiguous
word depends on what happens in other scenes, and that needs reasoning. `low` costs a few
cents less per episode and still catches outright mistranslations. Raise to `high` only for
dense or literary material.

**Minimum severity.** `minor` reports everything. Use `major` on a translation you mostly
trust and want only clear errors changed. `critical` restricts it to reversed or destroyed
meaning, which is the setting for a file you are reluctant to touch at all.

**Change cap.** A review that wants to rewrite more than 30% of the cues is refused whole and
reported, because at that rate it is rewriting the style rather than correcting errors. Three
corrections are always allowed however short the file, so a ten-line clip is not blocked by
its own size. Raise the cap when you are deliberately reviewing a poor translation.

**Cost ceiling.** The estimate is made before the call and is deliberately pessimistic about
how much the model will write. If the ceiling stops a legitimate run on a very long file,
raise it rather than lowering the review's scope. `0` disables the check.

### Hardcoded (by design)

- The transcript is divided into scenes at 2.0 s gaps (`proofread/document.py`), on purpose
  much shorter than the 30 s that `SrtFile` uses to plan DeepL requests. Here a scene is only
  a visual break in the transcript, and a short pause already separates two exchanges
- One call per file, unless the transcript exceeds 150,000 estimated tokens
- Batches never split a scene; oversized scenes go out whole
- Temperature 0.2, so two runs over the same file broadly agree
- The guard list itself: what a correction may not change is not user-configurable
- The model never sees markup. A fully italic cue gets its italics back after a correction;
  a partly italic cue is never rewritten (rejection reason `italic_markup`)

### Reading the report

Every run writes `<output>.proofread.json`.

```bash
python3 -c "
import json; d = json.load(open('movie_fi.srt.proofread.json'))
print(d['status'], d['cost_usd'], d['usage'])
for p in d['applied']:
    print(f\"[{p['id']}] {p['category']}/{p['severity']}: {p['before']!r} -> {p['after']!r}\")
for p in d['rejected']:
    print(f\"[{p['id']}] REJECTED {p['rejected_reason']}\")
"
```

A run with many `stale_precondition` rejections means the model is not quoting cues accurately
and its patches should not be trusted. Frequent `too_long` means the source is verbose and the
cues are tight, not that the review is wrong. `italic_markup` only means the cue was partly
italic.

### Checking a review before applying it

```bash
srtranslator movie_fi.srt --proofread-only --source movie.srt -i en -o fi --proofread-dry-run
```

The report is written in the same shape as a real run, so a dry run can be diffed against the
run that follows it.

## Current Implementation Notes

### What's Configurable Now
- Scene gap and context budgets: the constants at the top of `srtranslator/srt_file.py`
- Request size: `max_char` and `max_items` on the translator class
- Merge limits: the `MERGE_*` constants in `srtranslator/preprocess.py`
- Global context: via the `--context` CLI argument
- Model type: via the `--model-type` CLI argument
- Custom instructions: via `--instruction` and `--instruction-preset`
- Proof-reading: via the `--proofread-*` CLI arguments, see above

### What's Hardcoded (by design)
- Context format: plain source lines in reading order, no numbers or headings
- Context stops at the resume point of a resumed run
- A wrong cue count stops the run instead of pairing cues with the wrong text
- Each suspect cue is retried once, alone

## Debugging

### Enable Debug Mode
```bash
DEBUG_CONTEXT=1 python -m srtranslator file.srt ...
```

### What Debug Shows
- Number of scenes detected and requests planned
- Line range of each request
- Complete context sent to DeepL

### Interpreting Debug Output
```
Detected 14 scenes, planned 9 requests

============================================================
[Chunk 3] Lines 112-161
Context:
Line before the request.
Another line before it.
First line of the request.
...
Last line of the request.
Line after the request.
============================================================
```

**Check for:**
- The request's own lines appear in the middle of the context, in order
- No line before the resume point on a resumed run
- Request boundaries fall at long pauses

Run with `-v` to see the cues that were flagged for the proof-reader, the number of cues over
25 characters per second, and the characters DeepL billed.

## Recommended Workflow

### 1. Start with Defaults
```bash
export DEEPL_API_KEY=...
srtranslator movie.srt \
  --translator deepl-api \
  --src-lang en \
  --dest-lang fi \
  --filter-sdh \
  --merge-fragments \
  --instruction-preset fi
```

### 2. Add Global Context
```bash
--context "Genre and tone description"
```

### 3. Enable Debug (first run)
```bash
DEBUG_CONTEXT=1 srtranslator ...
```

### 4. Review the Requests
- Check that request boundaries fall at real pauses
- Change `SCENE_GAP_SECONDS` in `srt_file.py` only if they do not

### 5. Production Run
```bash
# Disable debug for clean output
srtranslator file.srt \
  --translator deepl-api \
  --src-lang en \
  --dest-lang fi \
  --filter-sdh \
  --merge-fragments \
  --instruction-preset fi \
  --context "TV drama. Natural dialogue." \
  --output file.fi.srt
```

`srtranslator-trans` runs this same pipeline with `--wrap-limit 42` and Plex-style output
names. See the README.

## Cost Optimization

### DeepL context is free
- Only the `text` array counts toward billing
- Use generous context limits
- Don't sacrifice quality to save context chars
- A retried cue is billed again, but only that cue

### Proof-reading is not free
- Roughly $0.03 to $0.06 per 45-minute episode on `gemini-3.8-flash`
- Input is the whole programme in both languages, about 20,000 to 25,000 tokens
- Output is small: only the cues that need correcting, plus thinking tokens
- `--proofread-max-cost` (default $0.50) stops a run before it starts, not after
- Every report records the measured usage and cost, so the estimate can be checked
- Rates verified September 2026 and scheduled to double on 1 January 2027

### Chunking Strategy
- `deepl-api`: up to 5000 characters and 50 cues per request
- Whole scenes where they fit; an oversized scene is split at its longest pause
- Requests always hold complete subtitle cues

### API Calls
- One call per request, plus one per retried cue
- Request size is set by `translator.max_char` and `translator.max_items`
- Context doesn't affect call count

---

**Bottom line:** The current defaults are well-tuned for subtitle translation. Provide
meaningful `--context`, use `--filter-sdh` and `--merge-fragments` on hearing-impaired or
choppy sources, and use `--instruction-preset fi` for Finnish. Leave proof-reading on its
defaults unless a report tells you otherwise.
