# SRTranslator Configuration Guide

## Context Window Settings

### Default Values (Optimized for Movies/Series)

```python
# Scene detection
scene_gap_seconds = 2.0          # Time gap to detect new scenes

# Context history limits
max_history_chars_before = 2000  # Previous dialogue (~15-20 subtitle lines)
max_history_chars_after = 1000   # Upcoming dialogue (~8-10 subtitle lines)
max_summary_chars = 2000         # Distant scene summary

# Distant history trigger
distant_history_threshold = 5    # Lines beyond history_before to trigger summary
```

### When to Adjust

#### Shorter Context (for real-time/fast translation)
```python
max_history_chars_before = 1000  # ~8-10 lines
max_history_chars_after = 500    # ~4-5 lines
max_summary_chars = 1000         # Smaller summary
```

#### Longer Context (for complex narratives)
```python
max_history_chars_before = 3000  # ~20-25 lines
max_history_chars_after = 1500   # ~12-15 lines
max_summary_chars = 3000         # Larger summary
```

#### Disable Distant Summaries
```python
distant_history_threshold = 999999  # Effectively disable
# or set max_summary_chars = 0
```

## Scene Detection Settings

### Default: 2.0 seconds
- Works well for most content
- Captures scene changes, location shifts
- Prevents context bleeding across cuts

### Adjust for specific content:

**Slow-paced dramas (more continuity):**
```python
scene_gap_seconds = 3.0  # Require longer gaps
```

**Fast-paced action (more breaks):**
```python
scene_gap_seconds = 1.5  # Shorter gaps trigger new scene
```

**Continuous dialogue (minimal breaks):**
```python
scene_gap_seconds = 4.0  # Only major scene changes
```

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

**Prefer quality with fallback:**
```bash
--model-type prefer_quality_optimized
```
- Tries next-gen first
- Falls back to classic if needed

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

- Scene detection reuses the 2.0 s gap rule, so the reviewer sees the same scenes DeepL did
- One call per file, unless the transcript exceeds 150,000 estimated tokens
- Batches never split a scene; oversized scenes go out whole
- Temperature 0.2, so two runs over the same file broadly agree
- The guard list itself: what a correction may not change is not user-configurable

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
cues are tight, not that the review is wrong.

### Checking a review before applying it

```bash
srtranslator movie_fi.srt --proofread-only --source movie.srt -i en -o fi --proofread-dry-run
```

The report is written in the same shape as a real run, so a dry run can be diffed against the
run that follows it.

## Current Implementation Notes

### What's Configurable Now
- Scene gap threshold: Change in `_detect_scenes(scene_gap_seconds=2.0)`
- History limits: Passed to `_build_deepl_context()`
- Global context: Via `--context` CLI argument
- Model type: Via `--model-type` CLI argument
- Proof-reading: Via the `--proofread-*` CLI arguments, see below

### What's Hardcoded (by design)
- Line number format: `{line_num}. {content}`
- Context structure: `Scene N\nPrevious dialogue:\n...`
- Truncation at 50 chars for distant summaries
- Word-boundary aware truncation

### Future Enhancement Possibilities

**Cross-scene continuity (not implemented):**
```python
# Potential addition for multi-episode story arcs:
def _build_episode_context():
    """Very compressed summary of previous scenes in episode"""
    # Would add another section:
    # "Earlier in this episode: [compressed summaries]"
```

**Character-aware context:**
```python
# Extract character names and track who's speaking
# Provide character-specific context
```

**Context bleed prevention:**
```python
# Add explicit prefix if needed (currently not necessary):
context = "CONTEXT (do not translate):\n" + context
```

## Debugging

### Enable Debug Mode
```bash
DEBUG_CONTEXT=1 python -m srtranslator file.srt ...
```

### What Debug Shows
- Number of scenes detected
- Line ranges for each chunk
- Complete context sent to DeepL
- Scene boundaries

### Interpreting Debug Output
```
============================================================
[Chunk 3] Lines 15-20
Context:
Scene 1

Previous dialogue:
12. Character speaks.
13. Another line.

Upcoming dialogue:
22. Future line.
23. More context.
============================================================
```

**Check for:**
- ✅ Context doesn't include lines 15-20 (current chunk)
- ✅ Line numbers are sequential within scene
- ✅ No scene boundary crossing
- ✅ Reasonable amount of context (not too sparse/dense)

## Recommended Workflow

### 1. Start with Defaults
```bash
srtranslator movie.srt \
  --translator deepl-api \
  --auth "YOUR_KEY" \
  --model-type quality_optimized
```

### 2. Add Global Context
```bash
--context "Genre and tone description"
```

### 3. Enable Debug (first run)
```bash
DEBUG_CONTEXT=1 srtranslator ...
```

### 4. Review Scene Detection
- Check if scenes align with actual content
- Adjust `scene_gap_seconds` if needed

### 5. Production Run
```bash
# Disable debug for clean output
srtranslator file.srt \
  --translator deepl-api \
  --auth "KEY" \
  --src-lang en \
  --dest-lang fi \
  --context "TV drama. Natural dialogue." \
  --model-type quality_optimized
```

## Cost Optimization

### DeepL context is free
- Only the `text` array counts toward billing
- Use generous context limits
- Don't sacrifice quality to save context chars

### Proof-reading is not free
- Roughly $0.03 to $0.06 per 45-minute episode on `gemini-3.8-flash`
- Input is the whole programme in both languages, about 20,000 to 25,000 tokens
- Output is small: only the cues that need correcting, plus thinking tokens
- `--proofread-max-cost` (default $0.50) stops a run before it starts, not after
- Every report records the measured usage and cost, so the estimate can be checked
- Rates verified September 2026 and scheduled to double on 1 January 2027

### Chunking Strategy
- Default: 1500 chars per chunk (DeepL limit)
- Ensures complete subtitle lines
- Automatic batching

### API Calls
- One call per chunk
- Chunk size determined by `translator.max_char`
- Context doesn't affect call count

---

**Bottom line:** The current defaults are well-tuned for subtitle translation. Adjust
`scene_gap_seconds` based on your content's pacing, and provide meaningful `--context` for best
results. Leave proof-reading on its defaults unless a report tells you otherwise. Everything
else should work optimally out of the box.
