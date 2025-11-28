import os
import re
import srt

from srt import Subtitle
from typing import List, Generator

from .translators.base import Translator
from .util import show_progress


class SrtFile:
    """SRT file class abstraction

    Args:
        filepath (str): file path of srt
    """

    def __init__(self, filepath: str, progress_callback=show_progress) -> None:
        self.filepath = filepath
        self.backup_file = f"{self.filepath}.tmp"
        self.subtitles = []
        self.start_from = 0
        self.current_subtitle = 0
        self.progress_callback = progress_callback

        print(f"Loading {filepath} as SRT")
        with open(filepath, "r", encoding="utf-8", errors="ignore") as input_file:
            self.subtitles = self.load_from_file(input_file)

        self._load_backup()

    def _load_backup(self):
        if not os.path.exists(self.backup_file):
            return

        print(f"Backup file found = {self.backup_file}")
        with open(self.backup_file, "r", encoding="utf-8", errors="ignore") as input_file:
            subtitles = self.load_from_file(input_file)

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
        return self._clean_subs_content(subtitles)

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

    def _clean_subs_content(self, subtitles: List[Subtitle]) -> List[Subtitle]:
        """Cleans subtitles content and delete line breaks

        Args:
            subtitles (List[Subtitle]): List of subtitles

        Returns:
            List[Subtitle]: Same list of subtitles, but cleaned
        """
        cleanr = re.compile("<.*?>")

        for sub in subtitles:
            sub.content = cleanr.sub("", sub.content)
            sub.content = srt.make_legal_content(sub.content)
            sub.content = sub.content.strip()

            if sub.content == "":
                sub.content = "..."

            if all(sentence.startswith("-") for sentence in sub.content.split("\n")):
                sub.content = sub.content.replace("\n", "////")
                continue

            sub.content = sub.content.replace("\n", " ")

        return subtitles

    def wrap_lines(self, line_wrap_limit: int = 50) -> None:
        """Wrap lines in all subtitles in file

        Args:
            line_wrap_limit (int): Number of maximum characters in a line before wrap. Defaults to 50.
        """
        for sub in self.subtitles:
            sub.content = sub.content.replace("////", "\n")

            content = []
            for line in sub.content.split("\n"):
                if len(line) > line_wrap_limit:
                    line = self.wrap_line(line, line_wrap_limit)
                content.append(line)

            sub.content = "\n".join(content)

    def wrap_line(self, text: str, line_wrap_limit: int = 50) -> str:
        """Wraps a line of text without breaking any word in half

        Args:
            text (str): Line text to wrap
            line_wrap_limit (int): Number of maximum characters in a line before wrap. Defaults to 50.

        Returns:
            str: Text line wraped
        """
        wraped_lines = []
        for word in text.split():
            # Check if inserting a word in the last sentence goes beyond the wrap limit
            if len(wraped_lines) != 0 and len(wraped_lines[-1]) + len(word) < line_wrap_limit:
                # If not, add it to it
                wraped_lines[-1] += f" {word}"
                continue

            # Insert a new sentence
            wraped_lines.append(f"{word}")

        # Join sentences with line break
        return "\n".join(wraped_lines)

    def _detect_scenes(self, scene_gap_seconds: float = 2.0) -> List[int]:
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

    def _build_deepl_context(
        self,
        scene_index: int,
        chunk_start_idx: int,
        chunk_end_idx: int,
        scene_start_idx: int,
        scene_end_idx: int,
        max_history_chars_before: int = 2000,
        max_history_chars_after: int = 1000,
        max_summary_chars: int = 2000,
    ) -> str | None:
        """Build DeepL context parameter (llm-subtrans style).

        Context contains ONLY surrounding lines in source language, NOT the current chunk.

        Args:
            scene_index: Current scene number
            chunk_start_idx: First subtitle index in current chunk
            chunk_end_idx: Last subtitle index in current chunk
            scene_start_idx: First subtitle index in current scene
            scene_end_idx: Last subtitle index in current scene
            max_history_chars_before: Max chars for previous dialogue
            max_history_chars_after: Max chars for upcoming dialogue
            max_summary_chars: Max chars for distant scene summary

        Returns:
            str: Formatted context string for DeepL
        """
        # Build history_before: walk backwards from chunk_start_idx - 1
        history_before_lines = []
        current_before_chars = 0

        for i in range(chunk_start_idx - 1, scene_start_idx - 1, -1):
            line_content = self.subtitles[i].content.strip()
            if not line_content or line_content == "...":
                continue

            # Format: just the content
            formatted_line = line_content
            line_length = len(formatted_line) + 1  # +1 for space/newline

            if current_before_chars + line_length > max_history_chars_before:
                break

            history_before_lines.insert(0, formatted_line)  # Prepend to keep chronological
            current_before_chars += line_length

        # Build history_after: walk forwards from chunk_end_idx + 1
        history_after_lines = []
        current_after_chars = 0

        for i in range(chunk_end_idx + 1, scene_end_idx + 1):
            line_content = self.subtitles[i].content.strip()
            if not line_content or line_content == "...":
                continue

            formatted_line = line_content
            line_length = len(formatted_line) + 1

            if current_after_chars + line_length > max_history_chars_after:
                break

            history_after_lines.append(formatted_line)
            current_after_chars += line_length

        # Compose final context string (Natural text flow)
        context_parts = []

        # Add previous dialogue
        if history_before_lines:
            context_parts.extend(history_before_lines)

        # Add upcoming dialogue
        if history_after_lines:
            context_parts.extend(history_after_lines)

        return " ".join(context_parts) if context_parts else None

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

        # Detect scene boundaries
        scene_starts = self._detect_scenes()
        if os.environ.get("DEBUG_CONTEXT"):
            print(f"Detected {len(scene_starts)} scenes in subtitle file")

        # Build scene map (subtitle index -> (scene_idx, scene_start, scene_end))
        scene_map = {}
        for scene_idx, start_idx in enumerate(scene_starts):
            end_idx = (
                scene_starts[scene_idx + 1] - 1
                if scene_idx + 1 < len(scene_starts)
                else len(self.subtitles) - 1
            )
            for sub_idx in range(start_idx, end_idx + 1):
                scene_map[sub_idx] = (scene_idx, start_idx, end_idx)

        # For each chunk of the file (based on the translator capabilities)
        chunk_num = 0
        current_subtitle_idx = self.start_from

        for subs_slice in self._get_next_chunk(translator.max_char):
            chunk_num += 1
            chunk_start_idx = current_subtitle_idx
            chunk_end_idx = current_subtitle_idx + len(subs_slice) - 1

            # Get scene info for this chunk
            scene_idx, scene_start_idx, scene_end_idx = scene_map.get(
                chunk_start_idx, (0, chunk_start_idx, chunk_end_idx)
            )

            # Build text array (only lines to translate)
            text = [sub.content for sub in subs_slice]

            # Build DeepL context (surrounding lines, NOT current chunk)
            current_context = self._build_deepl_context(
                scene_idx,
                chunk_start_idx,
                chunk_end_idx,
                scene_start_idx,
                scene_end_idx,
            )

            # Debug output
            if os.environ.get("DEBUG_CONTEXT"):
                if current_context:
                    print(f"\n{'=' * 60}")
                    print(f"[Chunk {chunk_num}] Lines {chunk_start_idx + 1}-{chunk_end_idx + 1}")
                    print(f"Context:\n{current_context}")
                    print(f"{'=' * 60}")
                else:
                    print(f"\n[Chunk {chunk_num}] No context (start of scene)")

            # Translate with context
            translation = translator.translate(
                text, source_language, destination_language, context=current_context
            )

            # Update subtitles with translations
            if isinstance(translation, str):
                translation = translation.splitlines()
            for i in range(len(subs_slice)):
                subs_slice[i].content = translation[i]
                self.current_subtitle += 1
                current_subtitle_idx += 1

            self.progress_callback(len(self.subtitles), progress=self.current_subtitle)

        print("... Translation done")

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
