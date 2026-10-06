"""srtranslator-trans: translate subtitles with DeepL, Plex-style output names.

The DeepL helper the Stremio subtitles add-on and the command line both use. It
was the unversioned script /home/ubuntu/bin/trans until 2026-10-06. It runs the
full pipeline in-process: hearing-impaired filtering, sentence-fragment merging,
DeepL with scene context and a custom-instruction preset, Gemini proof-reading
(when credentials exist), then fix-finnish-subs for Finnish.

The DeepL key is read from DEEPL_API_KEY and never put on a command line.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __main__ as srtranslator_cli
from .presets import INSTRUCTION_PRESETS

DEFAULT_TARGET = "Finnish"
MODEL_TYPE = "quality_optimized"
WRAP_LIMIT = 42

#: Target languages, by code or English name, to DeepL target codes.
SUPPORTED_LANGUAGES = {
    "fi": "fi", "finnish": "fi",
    "el": "el", "greek": "el",
    "es": "es", "spanish": "es",
    "fr": "fr", "french": "fr",
    "de": "de", "german": "de",
    "it": "it", "italian": "it",
    "pt": "pt-PT", "portuguese": "pt-PT",
    "pt-br": "pt-BR", "brazilian": "pt-BR",
    "nl": "nl", "dutch": "nl",
    "pl": "pl", "polish": "pl",
    "ru": "ru", "russian": "ru",
    "ja": "ja", "japanese": "ja",
    "zh": "zh", "chinese": "zh",
    "sv": "sv", "swedish": "sv",
    "da": "da", "danish": "da",
    "nb": "nb", "no": "nb", "norwegian": "nb",
    "tr": "tr", "turkish": "tr",
    "cs": "cs", "czech": "cs",
    "hu": "hu", "hungarian": "hu",
    "ro": "ro", "romanian": "ro",
    "bg": "bg", "bulgarian": "bg",
    "uk": "uk", "ukrainian": "uk",
    "ko": "ko", "korean": "ko",
    "id": "id", "indonesian": "id",
}  # fmt: skip

# DeepL source languages (GET /v2/languages?type=source, 2026-10-06). Separate from
# SUPPORTED_LANGUAGES, which lists targets: a source code takes no region (PT, not pt-PT).
DEEPL_SOURCE_LANGUAGES = {
    "af", "an", "ar", "as", "ay", "az", "ba", "be", "bg", "bn", "br", "bs", "ca", "cs",
    "cy", "da", "de", "el", "en", "eo", "es", "et", "eu", "fa", "fi", "fr", "ga", "gl",
    "gn", "gu", "ha", "he", "hi", "hr", "ht", "hu", "hy", "id", "ig", "is", "it", "ja",
    "jv", "ka", "kk", "ko", "ky", "la", "lb", "ln", "lt", "lv", "mg", "mi", "mk", "ml",
    "mn", "mr", "ms", "mt", "my", "nb", "ne", "nl", "oc", "om", "pa", "pl", "ps", "pt",
    "qu", "ro", "ru", "sa", "sk", "sl", "sq", "sr", "st", "su", "sv", "sw", "ta", "te",
    "tg", "th", "tk", "tl", "tn", "tr", "ts", "tt", "uk", "ur", "uz", "vi", "wo", "xh",
    "yi", "zh", "zu",
}  # fmt: skip
SOURCE_LANGUAGE_ALIASES = {"no": "nb", "nn": "nb", "iw": "he"}

TEXT_SUBTITLE_CODECS = ("subrip", "srt", "ass", "ssa", "webvtt")

#: ISO 639-2 track tags (as MKV files carry them) to DeepL source codes.
TRACK_LANGUAGES = {
    "eng": "en", "swe": "sv", "nor": "nb", "nob": "nb", "nno": "nb", "dan": "da",
    "ger": "de", "deu": "de", "dut": "nl", "nld": "nl", "fre": "fr", "fra": "fr",
    "spa": "es", "por": "pt", "ita": "it", "fin": "fi", "pol": "pl", "rus": "ru",
    "jpn": "ja", "chi": "zh", "zho": "zh", "kor": "ko", "tur": "tr", "cze": "cs",
    "ces": "cs", "hun": "hu", "rum": "ro", "ron": "ro", "bul": "bg", "ukr": "uk",
    "gre": "el", "ell": "el", "est": "et", "lav": "lv", "lit": "lt", "slo": "sk",
    "slk": "sk", "slv": "sl", "ind": "id", "ara": "ar", "heb": "he", "tha": "th",
    "vie": "vi", "alb": "sq", "sqi": "sq",
}  # fmt: skip

#: "Show.S01E01.en.srt" -> "en": a language tag right before .srt.
_LANG_SUFFIX_RE = re.compile(r"\.([a-z]{2,3}(?:-[a-z]{2,3})?)\.srt$", re.IGNORECASE)


def get_language_code(lang_name: str) -> str:
    """DeepL target code for a language code or English name; exits if unknown."""
    code = SUPPORTED_LANGUAGES.get(lang_name.strip().lower())
    if not code:
        names = sorted({name.title() for name in SUPPORTED_LANGUAGES if len(name) > 3})
        print(f"❌ Error: Unsupported language '{lang_name}'", file=sys.stderr)
        print(f"Supported languages: {', '.join(names)}", file=sys.stderr)
        sys.exit(1)
    return code


def get_source_language_code(lang: str) -> str:
    """Map a source language to a DeepL source code, or 'auto' when DeepL lacks it."""
    raw = lang.strip().lower()
    if raw == "auto":
        return "auto"
    code = SUPPORTED_LANGUAGES.get(raw, raw).split("-")[0].lower()
    code = SOURCE_LANGUAGE_ALIASES.get(code, code)
    if code in DEEPL_SOURCE_LANGUAGES:
        return code
    print(
        f"⚠️  Source language '{lang}' is not a DeepL source language; letting DeepL detect it",
        file=sys.stderr,
    )
    return "auto"


def build_plex_output_path(input_path: Path, lang_code: str) -> Path:
    """movie.en.srt -> movie.fi.srt: strip language-like suffixes, add the target."""
    base = input_path.stem
    pattern = re.compile(r"\.[a-z]{2,3}(-[a-z]{2,3})?$", re.IGNORECASE)
    while match := pattern.search(base):
        base = base[: match.start()]
    # Lower case, as the add-on expects it: "pt-PT" is DeepL's code, the file is .pt-pt.srt.
    return input_path.with_name(f"{base}.{lang_code.lower()}.srt")


def track_source_language(tag: str) -> str:
    """DeepL source code for an MKV language tag, or "auto" when it is unknown."""
    tag = (tag or "").strip().lower()
    code = TRACK_LANGUAGES.get(tag, tag)
    return get_source_language_code(code) if code and code != "und" else "auto"


def extract_subtitle_from_mkv(
    mkv_file: Path, output_srt: Path, source_lang: str = "en"
) -> str | None:
    """Extract the best text subtitle track of an MKV into ``output_srt``.

    A track in the requested source language comes first (English when the
    source is auto), then any text track. When the file has only bitmap tracks,
    English text subtitles are downloaded with psubs instead.

    Returns the DeepL source code of the extracted subtitle ("auto" when its
    track is untagged), or None when nothing could be extracted.
    """
    print("📹 MKV file detected - extracting subtitles...\n")
    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        print("❌ Error: ffmpeg and ffprobe are required for MKV subtitle extraction")
        return None

    try:
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(mkv_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        streams = json.loads(res.stdout).get("streams", [])
    except Exception as error:  # noqa: BLE001 - reported to the user, then skipped
        print(f"❌ Error running ffprobe: {error}")
        return None

    tracks = []
    for position, stream in enumerate(s for s in streams if s.get("codec_type") == "subtitle"):
        tags = stream.get("tags", {})
        tracks.append(
            (
                stream.get("index", position),
                tags.get("language", "und"),
                tags.get("title", "No title"),
                stream.get("codec_name", "unknown"),
            )
        )
    if not tracks:
        print(f"❌ No subtitle tracks found in {mkv_file}")
        return None

    print("Available subtitle tracks:")
    for index, lang, title, codec in tracks:
        print(f"  Track {index}: {title} [{lang}] ({codec})")
    print()

    wanted = "en" if source_lang == "auto" else source_lang
    text_tracks = [
        (index, lang) for index, lang, _, codec in tracks if codec in TEXT_SUBTITLE_CODECS
    ]
    preferred = [
        (index, lang) for index, lang in text_tracks if track_source_language(lang) == wanted
    ]
    choice = (preferred or text_tracks or [None])[0]
    selected = choice[0] if choice else None

    if selected is None:
        print("⚠️  Only bitmap subtitle tracks found — downloading English text subtitles...\n")
        try:
            subprocess.run(["psubs", "-l", "en", str(mkv_file)], text=True, check=False)
        except FileNotFoundError:
            print("❌ psubs not found. Install it or add it to your PATH.")
            return None
        en_srt = mkv_file.with_name(mkv_file.stem + ".en.srt")
        if not en_srt.exists():
            print("❌ psubs did not produce an English subtitle file")
            return None
        # psubs' download is kept as the English sidecar; the run reads a copy.
        shutil.copyfile(en_srt, output_srt)
        return "en"

    print(f"Selected track: {selected}\nExtracting to: {output_srt}\n")
    try:
        subprocess.run(
            ["ffmpeg", "-i", str(mkv_file), "-map", f"0:{selected}", "-c:s", "srt",
             str(output_srt), "-y"],
            capture_output=True,
            text=True,
            check=True,
        )  # fmt: skip
    except subprocess.CalledProcessError as error:
        print(f"❌ Extraction failed\n{error.stderr}")
        return None
    if not output_srt.exists():
        return None
    assert choice is not None
    return track_source_language(choice[1])


def build_srtranslator_argv(
    srt_file: Path, output_file: Path, source_lang: str, target_lang: str
) -> list[str]:
    """Arguments for the srtranslator pipeline, without the API key."""
    argv = [
        str(srt_file),
        "--translator", "deepl-api",
        "--dest-lang", target_lang,
        "--model-type", MODEL_TYPE,
        "--output", str(output_file),
        "--filter-sdh",
        "--merge-fragments",
        "--wrap-limit", str(WRAP_LIMIT),
        "-v",
    ]  # fmt: skip
    if source_lang != "auto":
        argv += ["--src-lang", source_lang]
    preset = target_lang.split("-")[0].lower()
    if preset in INSTRUCTION_PRESETS:
        argv += ["--instruction-preset", preset]
    return argv


def process_single_file(
    input_file: Path, debug_mode: bool, target_lang: str, source_lang: str
) -> bool:
    extracted_srt: Path | None = None
    srt_file = input_file

    if input_file.suffix.lower() == ".mkv":
        sidecar_lang = "en" if source_lang == "auto" else source_lang
        sidecar = input_file.with_name(f"{input_file.stem}.{sidecar_lang}.srt")
        if sidecar.exists():
            print(f"📄 Found existing subtitle: {sidecar.name}\n")
            srt_file = sidecar
            source_lang = sidecar_lang
        else:
            # A file of our own: a subtitle already beside the MKV (movie.srt) is
            # never overwritten or deleted.
            handle, temp_name = tempfile.mkstemp(
                prefix=f"{input_file.stem}.", suffix=".extracted.srt", dir=input_file.parent
            )
            os.close(handle)
            extracted_srt = Path(temp_name)
            extracted_lang = extract_subtitle_from_mkv(input_file, extracted_srt, source_lang)
            if extracted_lang is None:
                extracted_srt.unlink(missing_ok=True)
                print("❌ Failed to extract subtitles from MKV")
                return False
            if extracted_lang != source_lang:
                print(f"ℹ️  Extracted track is '{extracted_lang}', translating from that")
                source_lang = extracted_lang
            srt_file = extracted_srt

    output_file = build_plex_output_path(input_file, target_lang)
    print(f"Input:  {srt_file}\nOutput: {output_file}")
    print(f"Source: {source_lang} → Target: {target_lang} ({MODEL_TYPE})\n")

    # A backup left by an earlier failed run may come from a different version of
    # the pipeline, and resuming from it would pair cues with the wrong text.
    leftover = Path(f"{srt_file}.tmp")
    if leftover.exists():
        print("⚠️  Found leftover backup file from previous run, removing...")
        leftover.unlink()

    if debug_mode:
        os.environ["DEBUG_CONTEXT"] = "1"
    # -v makes srtranslator report billing and the proof-read result; the DeepL
    # client would add two lines per request at that level.
    logging.getLogger("deepl").setLevel(logging.WARNING)

    try:
        status = srtranslator_cli.main(
            build_srtranslator_argv(srt_file, output_file, source_lang, target_lang)
        )
    finally:
        if extracted_srt and extracted_srt.exists():
            extracted_srt.unlink()

    if status != 0:
        print(f"\n❌ Translation failed (exit {status})", file=sys.stderr)
        return False
    if not output_file.exists():
        print(f"\n❌ Error: Translation output not found: {output_file}", file=sys.stderr)
        return False
    print(f"\n✅ Translation complete: {output_file}")
    return True


def get_episode_sort_key(filepath: Path) -> str:
    match = re.search(r"S(\d+)E(\d+)", filepath.name, re.IGNORECASE)
    if match:
        return f"{int(match.group(1)):02d}{int(match.group(2)):03d}"
    return f"99999_{filepath.name}"


def is_already_translated(filepath: Path) -> bool:
    return bool(_LANG_SUFFIX_RE.search(filepath.name))


def batch_sources(files: list[Path], source_lang: str, target_lang: str) -> list[Path]:
    """The subtitles in a folder that are translation sources.

    An untagged file is a source, and so is one tagged with the source
    language (Show.S01E01.en.srt for -s en). A file in the target language, or in
    any other language when the source is fixed, is not. Two sources that would
    write the same output keep only the first, untagged before tagged.
    """
    target = target_lang.lower()
    chosen: dict[Path, Path] = {}
    for path in sorted(files, key=lambda f: (bool(_LANG_SUFFIX_RE.search(f.name)), f.name)):
        match = _LANG_SUFFIX_RE.search(path.name)
        tag = match.group(1).lower() if match else None
        if tag == target or (tag and source_lang != "auto" and tag != source_lang):
            continue
        output = build_plex_output_path(path, target_lang)
        chosen.setdefault(output, path)
    return sorted(chosen.values(), key=get_episode_sort_key)


def batch_process(files: list[Path], debug_mode: bool, target_lang: str, source_lang: str) -> int:
    to_process = [f for f in files if not build_plex_output_path(f, target_lang).exists()]
    skipped = len(files) - len(to_process)
    if not to_process:
        print(f"✅ All files already have {target_lang} subtitles (skipped {skipped})")
        return 0

    print(f"Found {len(to_process)} file(s) to process (skipped {skipped})\n")
    failed = 0
    for number, path in enumerate(to_process, start=1):
        print(f"━━━ ({number}/{len(to_process)}) {path.name}")
        if not process_single_file(path, debug_mode, target_lang, source_lang):
            failed += 1
    print(f"\nProcessed {len(to_process) - failed}, failed {failed}, skipped {skipped}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="srtranslator-trans",
        description=(
            "Translate subtitles with DeepL into <name>.<lang>.srt. With no file, "
            "translates every untranslated .srt in the current directory in episode "
            "order, or the .mkv files when there are none."
        ),
    )
    parser.add_argument(
        "-s", "--source-lang", dest="source_lang", default="en",
        help="Source language (default: en; 'auto' lets DeepL detect it)",
    )  # fmt: skip
    parser.add_argument(
        "-l", "--language", dest="target_lang", default=DEFAULT_TARGET,
        help=f"Target language (default: {DEFAULT_TARGET})",
    )  # fmt: skip
    parser.add_argument(
        "--debug", action="store_true", help="Print the context sent to DeepL for each request"
    )
    parser.add_argument("input_file", nargs="?", default=None, help="Single SRT or MKV file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.environ.get("DEEPL_API_KEY", "").strip():
        print("❌ Error: DEEPL_API_KEY environment variable is not set", file=sys.stderr)
        return 1

    target_lang = get_language_code(args.target_lang)
    source_lang = get_source_language_code(args.source_lang)

    if args.input_file:
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"❌ Error: File '{input_path}' not found", file=sys.stderr)
            return 1
        return 0 if process_single_file(input_path, args.debug, target_lang, source_lang) else 1

    cwd = Path.cwd()
    sources = batch_sources(list(cwd.glob("*.srt")), source_lang, target_lang)
    if not sources:
        sources = sorted(cwd.glob("*.mkv"), key=get_episode_sort_key)
    if not sources:
        print("❌ No SRT or MKV files found in current directory", file=sys.stderr)
        return 1
    return batch_process(sources, args.debug, target_lang, source_lang)


if __name__ == "__main__":
    sys.exit(main())
