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

## Current Implementation Notes

### What's Configurable Now
- Scene gap threshold: Change in `_detect_scenes(scene_gap_seconds=2.0)`
- History limits: Passed to `_build_deepl_context()`
- Global context: Via `--context` CLI argument
- Model type: Via `--model-type` CLI argument

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
python -m srtranslator movie.srt \
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
DEBUG_CONTEXT=1 python -m srtranslator ...
```

### 4. Review Scene Detection
- Check if scenes align with actual content
- Adjust `scene_gap_seconds` if needed

### 5. Production Run
```bash
# Disable debug for clean output
python -m srtranslator file.srt \
  --translator deepl-api \
  --auth "KEY" \
  --src-lang en \
  --dest-lang fi \
  --context "TV drama. Natural dialogue." \
  --model-type quality_optimized
```

## Cost Optimization

### Context is Free
- Only `text` array counts toward billing
- Use generous context limits
- Don't sacrifice quality to save context chars

### Chunking Strategy
- Default: 1500 chars per chunk (DeepL limit)
- Ensures complete subtitle lines
- Automatic batching

### API Calls
- One call per chunk
- Chunk size determined by `translator.max_char`
- Context doesn't affect call count

---

**Bottom line:** The current defaults are well-tuned for subtitle translation. Adjust `scene_gap_seconds` based on your content's pacing, and provide meaningful `--context` for best results. Everything else should work optimally out of the box.
