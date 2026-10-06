import logging
import os
import re
from collections.abc import Generator

import srt
from srt import Subtitle

from . import preprocess
from .preprocess import strip_tags
from .translators.base import Translator
from .util import fit_context, show_progress

LOG = logging.getLogger("srtranslator")

#: A silence this long reads as a cut to the viewer. Chunks never straddle one
#: unless a single scene is too big for one request.
SCENE_GAP_SECONDS = 30.0

#: Source text sent as free DeepL context around each chunk, in characters.
CONTEXT_CHARS_BEFORE = 4000
CONTEXT_CHARS_AFTER = 2000

#: A translation identical to its source is only suspicious when the cue has
#: real words in it; "OK" or a name legitimately comes back unchanged.
UNTRANSLATED_MIN_LETTERS = 15

#: Above this a cue cannot be read in time. Reported, never sent for review:
#: shortening is fix-finnish-subs' job, not the reviewer's.
FAST_CPS = 25.0

#: SrtFile writes the line break of a dash-dialogue cue as this while in flight.
DIALOGUE_LINE_BREAK = "////"


class SrtFile:
    """SRT file class abstraction

    Args:
        filepath (str): file path of srt
        keep_italics (bool): keep <i> tags in the text sent for translation.
            Only for a translator that handles XML tags (deepl-api).
        filter_sdh (bool): remove hearing-impaired annotations first.
        merge_fragments (bool): join sentences split across two short cues.
    """

    def __init__(
        self,
        filepath: str,
        progress_callback=show_progress,
        *,
        keep_italics: bool = False,
        filter_sdh: bool = False,
        merge_fragments: bool = False,
    ) -> None:
        self.filepath = filepath
        self.backup_file = f"{self.filepath}.tmp"
        self.subtitles = []
        self.raw_contents = {}  # Store original content before placeholder mutations
        self.start_from = 0
        self.current_subtitle = 0
        self.progress_callback = progress_callback
        self.keep_italics = keep_italics
        #: Cue index -> why the translation of that cue looks wrong. Read by the
        #: proof-reading stage, which reviews these cues with extra care.
        self.attention: dict[int, str] = {}

        print(f"Loading {filepath} as SRT")
        with open(filepath, "rb") as input_file:
            text = preprocess.decode_subtitle_bytes(input_file.read())

        subtitles = list(srt.sort_and_reindex(list(srt.parse(text))))
        if filter_sdh:
            subtitles = preprocess.filter_sdh(subtitles)
        if merge_fragments:
            subtitles = preprocess.merge_continuations(subtitles)
        self.subtitles = self._clean_subs_content(subtitles)

        self._load_backup()

    def _load_backup(self):
        if not os.path.exists(self.backup_file):
            return

        print(f"Backup file found = {self.backup_file}")

        # load_from_file() runs _clean_subs_content(), which rewrites
        # self.raw_contents. The backup holds already translated text, so letting
        # it through would replace the source text of every resumed subtitle with
        # its own translation. Keep the source copy taken from the input file.
        source_contents = dict(self.raw_contents)

        with open(self.backup_file, encoding="utf-8", errors="ignore") as input_file:
            subtitles = self.load_from_file(input_file)

            self.raw_contents = source_contents
            self.start_from = len(subtitles)
            self.current_subtitle = self.start_from
            print(f"Starting from subtitle {self.start_from}")
            self.subtitles = [
                *subtitles,
                *self.subtitles[self.start_from :],
            ]

    def load_from_file(self, input_file):
        srt_file = srt.parse(input_file)
        subtitles = list(srt_file)
        subtitles = list(srt.sort_and_reindex(subtitles))
        # A backup holds finished translations, one per source cue. Dropping an
        # empty one would shift every cue after it onto the wrong source.
        return self._clean_subs_content(subtitles, drop_empty=False)

    def _get_next_chunk(self, chunk_size: int = 4500) -> Generator:
        """Get a portion of the subtitles at the time based on the chunk size

        Args:
            chunk_size (int, optional): Maximum number of letter in text chunk. Defaults to 4500.

        Yields:
            Generator: Each chunk at the time
        """
        portion = []

        for subtitle in self.subtitles[self.start_from :]:
            # Calculate new chunk size if subtitle content is added to actual chunk
            n_char = (
                sum(len(sub.content) for sub in portion)  # All subtitles in chunk
                + len(subtitle.content)  # New subtitle
                + len(portion)  # Break lines in chunk
                + 1  # New breakline
            )

            # If chunk goes beyond the limit, yield it
            if n_char >= chunk_size and len(portion) != 0:
                yield portion
                portion = []

            # Put subtitle content in chunk
            portion.append(subtitle)

        # Yield last chunk
        yield portion

    def _clean_subs_content(
        self, subtitles: list[Subtitle], drop_empty: bool = True
    ) -> list[Subtitle]:
        """Cleans subtitles content and delete line breaks.
        Also stores raw content before placeholder mutations for context building.

        A cue with no readable text is dropped and the rest renumbered. Sending
        it as "..." used to put an empty subtitle on screen after translation.

        Args:
            subtitles (List[Subtitle]): List of subtitles

        Returns:
            List[Subtitle]: The cues that keep text, cleaned and renumbered
        """
        kept = []
        for sub in subtitles:
            content = preprocess.clean_markup(sub.content, keep_italics=self.keep_italics)
            content = srt.make_legal_content(content).strip()
            if drop_empty and not strip_tags(content).strip():
                continue
            sub.content = content
            kept.append(sub)

        for number, sub in enumerate(kept, start=1):
            sub.index = number

            # Store raw content BEFORE placeholder mutations (for context building)
            # Convert line breaks to spaces for clean context
            raw_content = " ".join(strip_tags(sub.content).split())
            self.raw_contents[sub.index] = raw_content

            lines = strip_tags(sub.content).split("\n")
            if all(line.lstrip().startswith("-") for line in lines):
                sub.content = sub.content.replace("\n", DIALOGUE_LINE_BREAK)
                continue

            sub.content = sub.content.replace("\n", " ")

        return kept

    def wrap_lines(
        self,
        line_wrap_limit: int = 50,
        use_cps: bool = False,
        target_cps: float = 17.0,
        max_lines: int = 2,
    ) -> None:
        """Wrap lines in all subtitles in file

        Args:
            line_wrap_limit (int): Number of maximum characters in a line before wrap. Defaults to 50.
            use_cps (bool): If True, calculate wrap limit based on subtitle duration and target CPS.
            target_cps (float): Target characters per second (default 17 for Finnish readability).
            max_lines (int): Maximum number of lines per subtitle. Defaults to 2.
        """
        for sub in self.subtitles:
            sub.content = sub.content.replace("////", "\n")

            # Calculate duration-based wrap limit if CPS mode is enabled
            if use_cps:
                duration = (sub.end - sub.start).total_seconds()
                max_chars = int(duration * target_cps)
                # Distribute across max_lines
                effective_limit = max(20, max_chars // max_lines)
            else:
                effective_limit = line_wrap_limit

            content = []
            for line in sub.content.split("\n"):
                if len(line) > effective_limit:
                    line = self.wrap_line(line, effective_limit, max_lines)
                content.append(line)

            sub.content = "\n".join(content)

    @staticmethod
    def wrap_line(text: str, line_wrap_limit: int = 50, max_lines: int = 2) -> str:
        """Wraps a line of text without breaking any word in half

        Static so the proof-reading stage can re-wrap a single corrected cue
        without holding an SrtFile.

        Args:
            text (str): Line text to wrap
            line_wrap_limit (int): Number of maximum characters in a line before wrap. Defaults to 50.
            max_lines (int): Maximum number of lines. Defaults to 2.

        Returns:
            str: Text line wrapped
        """
        wrapped_lines = []
        for word in text.split():
            # Check if inserting a word in the last sentence goes beyond the wrap limit
            if len(wrapped_lines) != 0 and len(wrapped_lines[-1]) + len(word) + 1 < line_wrap_limit:
                # If not, add it to it
                wrapped_lines[-1] += f" {word}"
                continue

            # Check if we've reached max lines and need to append to last line
            if len(wrapped_lines) >= max_lines:
                wrapped_lines[-1] += f" {word}"
                continue

            # Insert a new sentence
            wrapped_lines.append(f"{word}")

        # Join sentences with line break
        return "\n".join(wrapped_lines)

    def _detect_scenes(self, scene_gap_seconds: float = SCENE_GAP_SECONDS) -> list[int]:
        """Detect scene boundaries based on time gaps between subtitles.

        Args:
            scene_gap_seconds (float): Minimum gap in seconds to consider a new scene

        Returns:
            List[int]: List of subtitle indices where new scenes start
        """
        scene_starts = [0]  # First subtitle is always a scene start

        for i in range(1, len(self.subtitles)):
            prev_sub = self.subtitles[i - 1]
            curr_sub = self.subtitles[i]

            # Calculate gap between end of previous and start of current
            gap = (curr_sub.start - prev_sub.end).total_seconds()

            if gap >= scene_gap_seconds:
                scene_starts.append(i)

        return scene_starts

    def _plan_chunks(self, max_char: int, max_items: int | None = None) -> list[tuple[int, int]]:
        """Split the untranslated cues into requests that follow the scenes.

        Whole scenes are packed into one request while they fit. A scene too big
        for one request is split at its longest pause, recursively, so a chunk
        boundary always falls where the conversation pauses most. Ported from
        llm-subtrans SubtitleBatcher.

        Returns:
            Inclusive (first, last) positions in self.subtitles, in order.
        """
        start = self.start_from
        end = len(self.subtitles) - 1
        if start > end:
            return []

        def size(first: int, last: int) -> int:
            # Same measure as _get_next_chunk: text plus one break per cue.
            return sum(len(self.subtitles[i].content) + 1 for i in range(first, last + 1))

        def fits(first: int, last: int) -> bool:
            if max_items and last - first + 1 > max_items:
                return False
            return size(first, last) < max_char

        def split(first: int, last: int) -> list[tuple[int, int]]:
            if first == last or fits(first, last):
                return [(first, last)]
            # Cut after the cue followed by the longest pause.
            cut = max(
                range(first, last),
                key=lambda i: (self.subtitles[i + 1].start - self.subtitles[i].end).total_seconds(),
            )
            return split(first, cut) + split(cut + 1, last)

        blocks: list[tuple[int, int]] = []
        scene_starts = [s for s in self._detect_scenes() if s > start]
        bounds = [start, *scene_starts, end + 1]
        for first, next_first in zip(bounds, bounds[1:], strict=False):
            blocks.extend(split(first, next_first - 1))

        chunks: list[tuple[int, int]] = []
        for first, last in blocks:
            if chunks and fits(chunks[-1][0], last):
                chunks[-1] = (chunks[-1][0], last)
            else:
                chunks.append((first, last))
        return chunks

    def _context_line(self, position: int) -> str:
        sub = self.subtitles[position]
        return self.raw_contents.get(sub.index, strip_tags(sub.content).strip())

    def _build_deepl_context(
        self,
        chunk_start_idx: int,
        chunk_end_idx: int,
        max_chars_before: int = CONTEXT_CHARS_BEFORE,
        max_chars_after: int = CONTEXT_CHARS_AFTER,
    ) -> str | None:
        """Source text around a chunk, in reading order, for DeepL's context.

        DeepL translates each cue of a request on its own, so the context is the
        only place a cue can see its neighbours. It holds the lines before the
        chunk, the chunk's own lines, then the lines after it. Context is not
        billed. It may cross a scene boundary: names and topics carry over.

        Lines before ``start_from`` are never used: on a resumed run they hold
        already translated text, not source language.
        """
        before: list[str] = []
        used = 0
        for i in range(chunk_start_idx - 1, self.start_from - 1, -1):
            line = self._context_line(i)
            if not line:
                continue
            if used + len(line) + 1 > max_chars_before:
                break
            before.insert(0, line)
            used += len(line) + 1

        chunk = [
            line
            for line in (self._context_line(i) for i in range(chunk_start_idx, chunk_end_idx + 1))
            if line
        ]

        after: list[str] = []
        used = 0
        for i in range(chunk_end_idx + 1, len(self.subtitles)):
            line = self._context_line(i)
            if not line:
                continue
            if used + len(line) + 1 > max_chars_after:
                break
            after.append(line)
            used += len(line) + 1

        parts = before + chunk + after
        return "\n".join(parts) if parts else None

    def _needs_retry(self, position: int, translated: str) -> str | None:
        """Why a freshly translated cue must be asked for again, if it must."""
        sub = self.subtitles[position]
        visible = strip_tags(translated).replace(DIALOGUE_LINE_BREAK, " ").strip()
        if not visible:
            return "empty"
        source = self.raw_contents.get(sub.index, "")
        letters = sum(ch.isalpha() for ch in source)
        if letters >= UNTRANSLATED_MIN_LETTERS and " ".join(visible.split()) == source:
            return "untranslated"
        return None

    def translate(
        self,
        translator: Translator,
        source_language: str,
        destination_language: str,
    ) -> None:
        """Translate SRT file using a translator of your choose

        Args:
            translator (Translator): Translator object of choose
            destination_language (str): Destination language (must be coherent with your translator)
            source_language (str): Source language (must be coherent with your translator)
        """
        print("Starting translation")

        chunks = self._plan_chunks(translator.max_char, getattr(translator, "max_items", None))
        if os.environ.get("DEBUG_CONTEXT"):
            print(f"Detected {len(self._detect_scenes())} scenes, planned {len(chunks)} requests")

        for chunk_num, (chunk_start_idx, chunk_end_idx) in enumerate(chunks, start=1):
            subs_slice = self.subtitles[chunk_start_idx : chunk_end_idx + 1]
            text = [sub.content for sub in subs_slice]

            current_context = self._build_deepl_context(chunk_start_idx, chunk_end_idx)
            current_context = fit_context(current_context, text)

            if os.environ.get("DEBUG_CONTEXT"):
                print(f"\n{'=' * 60}")
                print(f"[Chunk {chunk_num}] Lines {chunk_start_idx + 1}-{chunk_end_idx + 1}")
                print(f"Context:\n{current_context}")
                print(f"{'=' * 60}")

            translation = translator.translate(
                text, source_language, destination_language, context=current_context
            )

            if isinstance(translation, str):
                translation = translation.splitlines()
            if len(translation) != len(subs_slice):
                # Raising keeps the cues translated so far in the .tmp backup;
                # zipping would pair every later cue with the wrong text.
                raise RuntimeError(
                    f"Translator returned {len(translation)} cues for a request of "
                    f"{len(subs_slice)} (lines {chunk_start_idx + 1}-{chunk_end_idx + 1})"
                )

            for offset, sub in enumerate(subs_slice):
                translated = translation[offset]
                reason = self._needs_retry(chunk_start_idx + offset, translated)
                if reason:
                    retried = translator.translate(
                        sub.content, source_language, destination_language, context=current_context
                    )
                    if isinstance(retried, list):
                        retried = retried[0] if retried else ""
                    if self._needs_retry(chunk_start_idx + offset, retried) is None:
                        translated = retried
                    else:
                        self.attention[sub.index] = reason
                sub.content = self._repair_markers(sub.content, translated, sub.index)
                self.current_subtitle += 1

            self.progress_callback(len(self.subtitles), progress=self.current_subtitle)

        self._log_reading_speed()
        print("... Translation done")

    def _repair_markers(self, source: str, translated: str, index: int) -> str:
        """Keep the dialogue placeholder only where the source had one.

        A placeholder in a cue that was not dialogue would become a stray line
        break; a dialogue cue that lost or gained speaker lines is flagged for
        review instead, because only a reader can tell where the turn changes.
        """
        source_turns = source.count(DIALOGUE_LINE_BREAK)
        if not source_turns:
            return " ".join(translated.replace(DIALOGUE_LINE_BREAK, " ").split())
        if translated.count(DIALOGUE_LINE_BREAK) != source_turns:
            self.attention.setdefault(index, "dialogue_lines")
        return translated

    def _log_reading_speed(self) -> None:
        fast = 0
        for sub in self.subtitles[self.start_from :]:
            duration = (sub.end - sub.start).total_seconds()
            chars = len(strip_tags(sub.content).replace(DIALOGUE_LINE_BREAK, ""))
            if duration > 0 and chars / duration > FAST_CPS:
                fast += 1
        if fast:
            LOG.info("%d cue(s) read faster than %.0f characters per second", fast, FAST_CPS)
        if self.attention:
            LOG.info(
                "%d cue(s) flagged for the proof-reader: %s", len(self.attention), self.attention
            )

    def save_backup(self):
        self.subtitles = self.subtitles[: self.current_subtitle]
        self.save(self.backup_file)

    def _delete_backup(self):
        if os.path.exists(self.backup_file):
            os.remove(self.backup_file)

    def save(self, filepath: str) -> None:
        """Saves SRT to file

        Args:
            filepath (str): Path of the new file
        """
        self._delete_backup()

        print(f"Saving {filepath}")
        subtitles = srt.compose(self.subtitles)
        with open(filepath, "w", encoding="utf-8") as file_out:
            file_out.write(subtitles)

    def validate(
        self,
        target_cps: float = 17.0,
        check_formality: bool = True,
        target_language: str = "fi",
    ) -> list[dict]:
        """Validate translated subtitles for quality issues.

        Args:
            target_cps (float): Maximum acceptable characters per second. Defaults to 17.
            check_formality (bool): Check for mixed formality (sinä/te for Finnish). Defaults to True.
            target_language (str): Target language code for language-specific checks. Defaults to "fi".

        Returns:
            List[dict]: List of warnings with line numbers and descriptions.
        """
        warnings = []

        # Finnish formality patterns
        fi_informal_patterns = [
            r"\bsä\b",
            r"\bsun\b",
            r"\bsut\b",
            r"\bsulla\b",
            r"\bsulle\b",
            r"\bsusta\b",
            r"\bsinä\b",
            r"\bsinun\b",
            r"\bsinua\b",
            r"\bsinulle\b",
            r"\bsinulta\b",
            r"\bsinusta\b",
        ]
        fi_formal_patterns = [
            r"\bte\b",
            r"\bteidän\b",
            r"\bteitä\b",
            r"\bteille\b",
            r"\bteiltä\b",
            r"\bteistä\b",
        ]

        # Track formality per scene for mixed formality detection
        scene_starts = self._detect_scenes()
        scene_formality = {}  # scene_idx -> {'informal': [lines], 'formal': [lines]}

        for i, sub in enumerate(self.subtitles):
            # Calculate CPS
            duration = (sub.end - sub.start).total_seconds()
            if duration > 0:
                content_length = len(strip_tags(sub.content).replace("\n", ""))
                cps = content_length / duration

                if cps > target_cps:
                    warnings.append(
                        {
                            "line": sub.index,
                            "type": "cps",
                            "severity": "warning" if cps < target_cps * 1.3 else "error",
                            "message": f"CPS={cps:.1f} exceeds target {target_cps} (content: {content_length} chars, duration: {duration:.1f}s)",
                        }
                    )

            # Check formality for Finnish
            if check_formality and target_language.lower() in ("fi", "fin", "finnish"):
                content_lower = sub.content.lower()

                # Find which scene this subtitle belongs to
                scene_idx = 0
                for j, start_idx in enumerate(scene_starts):
                    if i >= start_idx:
                        scene_idx = j

                if scene_idx not in scene_formality:
                    scene_formality[scene_idx] = {"informal": [], "formal": []}

                # Check for informal pronouns
                for pattern in fi_informal_patterns:
                    if re.search(pattern, content_lower):
                        scene_formality[scene_idx]["informal"].append(sub.index)
                        break

                # Check for formal pronouns
                for pattern in fi_formal_patterns:
                    if re.search(pattern, content_lower):
                        scene_formality[scene_idx]["formal"].append(sub.index)
                        break

        # Check for mixed formality within scenes
        if check_formality and target_language.lower() in ("fi", "fin", "finnish"):
            for scene_idx, formality in scene_formality.items():
                if formality["informal"] and formality["formal"]:
                    informal_lines = ", ".join(str(line) for line in formality["informal"][:3])
                    formal_lines = ", ".join(str(line) for line in formality["formal"][:3])
                    warnings.append(
                        {
                            "line": min(formality["informal"] + formality["formal"]),
                            "type": "formality",
                            "severity": "warning",
                            "message": f"Scene {scene_idx + 1}: Mixed formality detected - informal (lines {informal_lines}...) vs formal (lines {formal_lines}...)",
                        }
                    )

        return warnings

    def print_warnings(
        self,
        target_cps: float = 17.0,
        check_formality: bool = True,
        target_language: str = "fi",
    ) -> int:
        """Validate and print warnings for quality issues.

        Args:
            target_cps (float): Maximum acceptable characters per second.
            check_formality (bool): Check for mixed formality.
            target_language (str): Target language code.

        Returns:
            int: Number of warnings found.
        """
        warnings = self.validate(target_cps, check_formality, target_language)

        if not warnings:
            print("✓ No quality issues detected")
            return 0

        print(f"\n⚠️  Found {len(warnings)} quality issue(s):\n")

        for w in warnings:
            severity_icon = "⚠️" if w["severity"] == "warning" else "❌"
            print(f"  {severity_icon} Line {w['line']}: {w['message']}")

        print()
        return len(warnings)

    def postprocess(
        self,
        target_language: str = "fi",
        use_cps_wrapping: bool = True,
        target_cps: float = 17.0,
        line_wrap_limit: int = 50,
        max_lines: int = 2,
        validate_output: bool = True,
        check_formality: bool = True,
        run_external_fixer: bool = False,
        external_fixer_cmd: str = "fix-finnish-subs",
        fixer_args: list = None,
    ) -> dict:
        """Post-process translated subtitles with language-specific optimizations.

        This is the main entry point for subtitle post-processing, combining:
        - CPS-aware line wrapping
        - Quality validation
        - Optional external post-processor (e.g., fix-finnish-subs)

        Args:
            target_language (str): Target language code. Defaults to "fi".
            use_cps_wrapping (bool): Use CPS-based line wrapping. Defaults to True.
            target_cps (float): Target characters per second. Defaults to 17.
            line_wrap_limit (int): Fallback wrap limit if not using CPS. Defaults to 50.
            max_lines (int): Maximum lines per subtitle. Defaults to 2.
            validate_output (bool): Run validation checks. Defaults to True.
            check_formality (bool): Check for mixed formality (Finnish). Defaults to True.
            run_external_fixer (bool): Run external post-processor. Defaults to False.
            external_fixer_cmd (str): External command to run. Defaults to "fix-finnish-subs".
            fixer_args (list): Additional arguments for external fixer.

        Returns:
            dict: Results containing 'warnings' list and 'external_fixer_result' if applicable.
        """

        result = {
            "warnings": [],
            "external_fixer_result": None,
        }

        # Apply line wrapping
        self.wrap_lines(
            line_wrap_limit=line_wrap_limit,
            use_cps=use_cps_wrapping,
            target_cps=target_cps,
            max_lines=max_lines,
        )

        # Run validation
        if validate_output:
            result["warnings"] = self.validate(
                target_cps=target_cps,
                check_formality=check_formality,
                target_language=target_language,
            )

        # Run external fixer if requested (requires file to be saved first)
        if run_external_fixer:
            result["external_fixer_result"] = {
                "command": external_fixer_cmd,
                "note": "Call save() first, then run external fixer on the saved file path",
            }

        return result

    def run_external_fixer(
        self,
        filepath: str,
        command: str = "fix-finnish-subs",
        args: list = None,
    ) -> dict:
        """Run an external post-processing command on a saved subtitle file.

        Args:
            filepath (str): Path to the saved subtitle file.
            command (str): External command to run. Defaults to "fix-finnish-subs".
            args (list): Additional command arguments.

        Returns:
            dict: Result containing 'success', 'stdout', 'stderr', 'returncode'.
        """
        import subprocess

        cmd = [command, filepath]
        if args:
            cmd.extend(args)

        try:
            proc = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            return {
                "success": True,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Command '{command}' not found",
                "returncode": -1,
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "stdout": e.stdout,
                "stderr": e.stderr,
                "returncode": e.returncode,
            }
