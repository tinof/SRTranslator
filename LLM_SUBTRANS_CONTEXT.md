# LLM-Subtrans Style Context Implementation

## Summary of Changes

The subtitle translator now uses **llm-subtrans style context management**, providing DeepL with rich, structured context for maximum translation quality.

## Key Improvements

### 1. **Proper Context vs Text Separation**
- `text`: Contains **only** the lines being translated (array)
- `context`: Contains **surrounding dialogue** in source language (string, never translated)
- Current chunk lines are **never duplicated** in context

### 2. **Line-Numbered Context Format**
```
Scene 2

Previous dialogue:
12. Sarah walked into the room.
13. She looked worried.
14. The meeting had gone badly.

Upcoming dialogue:
18. John would have to fix this.
19. There was no other choice.
20. The board expected results.
```

### 3. **Configurable History Windows**
- **Previous dialogue**: Up to 2000 characters (walking backwards chronologically)
- **Upcoming dialogue**: Up to 1000 characters (looking ahead)
- **Scene summary**: Up to 2000 characters for distant history

### 4. **Scene Boundary Respect**
- Context **never crosses** scene boundaries
- Each scene starts fresh
- Scenes detected by time gaps (≥2 seconds)

### 5. **Distant History Summaries**
For long scenes where immediate context doesn't capture early dialogue:
```
Scene 1

Earlier in this scene:
The detective arrived### at the crime scene...
Witnesses were being interviewed...
Evidence was being collected...

Previous dialogue:
42. The suspect had an alibi.
43. But something didn't add up.

Upcoming dialogue:
46. She would need to dig deeper.
```

## Context Building Algorithm

```python
def _build_deepl_context(
    scene_index,          # Which scene (for labeling)
    chunk_start_idx,      # First line in current chunk
    chunk_end_idx,        # Last line in current chunk  
    scene_start_idx,      # First line of scene
    scene_end_idx,        # Last line of scene
    # Configurable limits:
    max_history_chars_before=2000,   # Previous dialogue limit
    max_history_chars_after=1000,    # Upcoming dialogue limit
    max_summary_chars=2000            # Distant summary limit
):
    # 1. Walk backwards from chunk_start - 1
    #    Format: "line_num. content"
    #    Stop at max_history_chars_before
    #    Keep chronological order
    
    # 2. Walk forwards from chunk_end + 1
    #    Format: "line_num. content"
    #    Stop at max_history_chars_after
    
    # 3. If there's distant history (>5 lines before history_before):
    #    Create truncated summary (50 chars per line)
    
    # 4. Compose final context:
    #    "Scene {N}\n"
    #    "[Earlier in this scene: ...]\n"
    #    "Previous dialogue:\n{lines}\n"
    #    "Upcoming dialogue:\n{lines}"
```

## Example Translation Flow

**Source Subtitles (English):**
```
1. Sarah entered the lab.
2. She looked at the samples.
3. Something was wrong.
4. The cultures had mutated.
5. This shouldn't be possible.
--- [translating chunk 3-4] ---
6. Dr. Chen needed to know immediately.
7. This could be dangerous.
```

**Context Sent to DeepL for Lines 3-4:**
```
Scene 1

Previous dialogue:
1. Sarah entered the lab.
2. She looked at the samples.

Upcoming dialogue:
5. This shouldn't be possible.
6. Dr. Chen needed to know immediately.
7. This could be dangerous.
```

**Text Sent (array):**
```
[
  "Something was wrong.",
  "The cultures had mutated."
]
```

**Result:**
DeepL understands:
- Sarah is the subject (from previous context)
- Scientific/lab setting (from context)  
- Urgency and danger (from upcoming context)
- Proper Finnish pronouns and medical terminology

## Benefits for Finnish Translation

### Pronoun Resolution
Finnish has gender-neutral "hän" but context determines usage:
```
Before: "He looked tired" → "Hän näytti väsyneeltä" (ambiguous)
With context showing "John" earlier → Correct masculine interpretation
```

### Topic Continuity
```
Line: "It was concerning."
Context: Previous mentions "The quarterly results"
Translation: "Se oli huolestuttavaa" (correctly refers to results)
```

### Tone Consistency
```
Global context: "Legal drama. Formal language."
Scene context: Previous lines show courtroom setting
Result: Proper formal Finnish legal terminology throughout scene
```

## Limits and Safeguards

### Character Limits
- `context` + `text` must stay under DeepL's 128 KiB limit
- Context typically capped at 4-8 KB per request
- History windows auto-truncate to stay within limits

### Word Boundaries
- Truncation respects word boundaries
- No mid-word cuts when trimming history

### Empty Line Handling
- Skips empty lines or "..." placeholders
- Only meaningful dialogue included in context

## Debug Mode

Enable with `DEBUG_CONTEXT=1` to see complete context:

```bash
DEBUG_CONTEXT=1 python -m srtranslator movie.srt \
  --translator deepl-api \
  --auth "YOUR_KEY" \
  --model-type quality_optimized
```

**Output:**
```
============================================================
[Chunk 2] Lines 11-15
Context:
Scene 1

Previous dialogue:
8. The experiment was ready.
9. Years of work led to this moment.
10. Everyone held their breath.

Upcoming dialogue:
16. But something went wrong.
17. The readings were impossible.
18. This defied all known physics.
============================================================
```

## Configuration Options

### Scene Detection
Default: 2.0 seconds gap = new scene

Customizable in code:
```python
scene_starts = self._detect_scenes(scene_gap_seconds=2.0)
```

### History Limits
Defaults optimized for subtitle translation:
- `max_history_chars_before=2000` - About 15-20 subtitle lines
- `max_history_chars_after=1000` - About 8-10 subtitle lines
- `max_summary_chars=2000` - For very long scenes

## Implementation Quality

✅ **Follows llm-subtrans methodology**
✅ **Context never duplicates current chunk**
✅ **Line numbers included for clarity**
✅ **Scene labeling**
✅ **Distant history summaries**
✅ **Fully debuggable output**
✅ **Word-boundary aware truncation**
✅ **Configurable limits**

## Comparison: Before vs After

### Before (Simple Bidirectional)
```
Context: "[Previous: some text] [Upcoming: some text]"
```
- No line numbers
- No scene labeling
- Limited to ~1000 chars total
- Hard to debug

### After (LLM-Subtrans Style)
```
Scene 2

Earlier in this scene:
<truncated distant history if needed>

Previous dialogue:
15. Full line with number
16. Another line
17. And another

Upcoming dialogue:
22. Future line
23. More future context
```
- Clear structure
- Line numbers for precise reference
- Scene awareness
- Up to 3000+ chars of context
- Easy to debug and verify

## Production Usage

**Recommended command:**
```bash
python -m srtranslator series_episode.srt \
  --translator deepl-api \
  --auth "YOUR_KEY" \
  --src-lang en \
  --dest-lang fi \
  --context "TV drama series. Natural conversational dialogue." \
  --model-type quality_optimized
``

This provides:
1. Global style guidance (`--context`)
2. Per-chunk scene-aware history (automatic)
3. Next-gen model quality (`quality_optimized`)
4. Proper context separation (built-in)

## Cost Impact

**Zero additional cost:**
- Context parameter is **free** in DeepL API
- Only `text` array counts toward billing
- Rich context improves quality without cost

---

**Result:** Professional-grade Finnish subtitles with proper context awareness, accurate pronouns,  consistent tone, and natural dialogue flow—matching the quality of llm-subtrans but using DeepL's context parameter instead of LLM summarization.
