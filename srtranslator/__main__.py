from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback

from .ass_file import AssFile
from .presets import instruction_preset
from .proofread import ProofreadOptions, proofread_pair, proofread_srt_file
from .proofread.backends import gemini as gemini_backend
from .proofread.models import ProofreadError
from .srt_file import SrtFile
from .translators.base import Translator
from .translators.deepl_api import DeeplApi
from .translators.deepl_scrap import DeeplTranslator
from .translators.pydeeplx import PyDeepLX
from .translators.translatepy import TranslatePy

LOG = logging.getLogger("srtranslator")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="srtranslator",
        description="Translate .srt and .ass subtitle files from the command line",
    )

    parser.add_argument(
        "filepath",
        metavar="path",
        type=str,
        help="Subtitle file to translate",
    )

    parser.add_argument(
        "-i",
        "--src-lang",
        type=str,
        default="auto",
        help="Source language. Default: auto",
    )

    parser.add_argument(
        "-o",
        "--dest-lang",
        type=str,
        default="es",
        help="Destination language. Default: es (Spanish)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        dest="loglevel",
        const=logging.INFO,
        help="Increase output verbosity",
    )

    parser.add_argument(
        "-vv",
        "--debug",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.WARNING,
        help="Increase output verbosity for debugging",
    )

    parser.add_argument(
        "-s",
        "--show-browser",
        action="store_true",
        help="Show browser window (Selenium-based translators)",
    )

    parser.add_argument(
        "-w",
        "--wrap-limit",
        type=int,
        default=50,
        help="Number of characters -including spaces- to wrap a line of text. Default: 50",
    )

    parser.add_argument(
        "--use-cps",
        action="store_true",
        help="Use CPS-based line wrapping instead of fixed character limit",
    )

    parser.add_argument(
        "--target-cps",
        type=float,
        default=17.0,
        help="Target characters per second for CPS-based wrapping and validation. Default: 17",
    )

    parser.add_argument(
        "--max-lines",
        type=int,
        default=2,
        help="Maximum number of lines per subtitle. Default: 2",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run quality validation after translation (CPS, formality checks)",
    )

    parser.add_argument(
        "--no-formality-check",
        action="store_true",
        help="Disable formality consistency checking (Finnish sinä/te)",
    )

    parser.add_argument(
        "-t",
        "--translator",
        type=str,
        choices=["deepl-scrap", "translatepy", "deepl-api", "pydeeplx"],
        help="Built-in translator to use",
        default="deepl-scrap",
    )

    parser.add_argument(
        "--auth",
        type=str,
        help=(
            "API key if needed by the translator. deepl-api reads $DEEPL_API_KEY when "
            "this is omitted, which keeps the key out of the process list"
        ),
    )

    parser.add_argument(
        "--output",
        type=str,
        metavar="PATH",
        default=None,
        help="Where to write the translation. Default: <input>_<dest-lang>.<ext>",
    )

    parser.add_argument(
        "--filter-sdh",
        action="store_true",
        help=(
            "Remove hearing-impaired annotations (sound effects, music, speaker labels) "
            "before translating. .srt only"
        ),
    )

    parser.add_argument(
        "--merge-fragments",
        action="store_true",
        help="Join a sentence split across two short cues before translating. .srt only",
    )

    parser.add_argument(
        "--proxies",
        action="store_true",
        help="Use proxy by default for pydeeplx",
    )

    parser.add_argument(
        "--context",
        type=str,
        help="Context for DeepL translation (only for deepl-api)",
    )

    parser.add_argument(
        "--model-type",
        type=str,
        choices=["quality_optimized", "latency_optimized", "prefer_quality_optimized"],
        default="quality_optimized",
        help=(
            "DeepL model type (only for deepl-api). quality_optimized is the "
            "next-generation model and the default. latency_optimized is the faster "
            "classic model. prefer_quality_optimized is a legacy alias of "
            "quality_optimized. Default: quality_optimized"
        ),
    )

    parser.add_argument(
        "--instruction",
        type=str,
        action="append",
        dest="custom_instructions",
        metavar="TEXT",
        help=(
            "DeepL custom instruction, repeatable (only for deepl-api). At most 10 "
            "instructions of 300 characters each, for example "
            "'Keep character names untranslated'"
        ),
    )

    parser.add_argument(
        "--instruction-preset",
        type=str,
        metavar="LANG",
        default=None,
        help=(
            "Add a built-in set of custom instructions for this target language "
            "(only for deepl-api). Available: fi"
        ),
    )

    parser.add_argument(
        "--glossary-id",
        type=str,
        metavar="ID",
        default=None,
        help=(
            "DeepL glossary to apply (only for deepl-api). Ignored when the source "
            "language is auto, because DeepL needs the language pair"
        ),
    )

    parser.add_argument(
        "--no-external-fixer",
        action="store_true",
        help="Disable running fix-finnish-subs after translation",
    )

    proofread = parser.add_argument_group(
        "AI proof-reading",
        "Review the finished translation against the original with a Gemini model, and "
        "correct only cues whose meaning came out wrong. Runs automatically when "
        "google-genai is installed and Gemini credentials are set.",
    )

    proofread.add_argument(
        "--proofread",
        dest="proofread",
        action="store_true",
        default=None,
        help="Force proof-reading on, and fail loudly if it cannot run",
    )

    proofread.add_argument(
        "--no-proofread",
        dest="proofread",
        action="store_false",
        help="Skip proof-reading even when credentials are available",
    )

    proofread.add_argument(
        "--proofread-only",
        action="store_true",
        help=(
            "Proof-read an already translated file instead of translating. The "
            "positional path is the translated subtitle, --source is the original. "
            "The file is edited in place and the previous version is kept as .bak"
        ),
    )

    proofread.add_argument(
        "--source",
        type=str,
        metavar="PATH",
        help="Original subtitle file, required by --proofread-only",
    )

    proofread.add_argument(
        "--proofread-model",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Reviewing model. Default: $SRTRANSLATOR_PROOFREAD_MODEL or "
            f"{gemini_backend.DEFAULT_MODEL}"
        ),
    )

    proofread.add_argument(
        "--proofread-thinking",
        type=str,
        choices=["low", "medium", "high"],
        default=None,
        help="Reasoning level of the reviewing model. Default: $GEMINI_THINKING_LEVEL or medium",
    )

    proofread.add_argument(
        "--proofread-min-severity",
        type=str,
        choices=["minor", "major", "critical"],
        default="minor",
        help="Ignore corrections below this severity. Default: minor",
    )

    proofread.add_argument(
        "--proofread-max-change",
        type=float,
        default=0.30,
        metavar="FRACTION",
        help=(
            "Refuse the whole review if it wants to change more than this share of "
            "the cues. Default: 0.30"
        ),
    )

    proofread.add_argument(
        "--proofread-max-cost",
        type=float,
        default=0.50,
        metavar="USD",
        help="Skip the review if it is estimated to cost more than this. 0 disables. Default: 0.50",
    )

    proofread.add_argument(
        "--proofread-report",
        type=str,
        default=None,
        metavar="PATH",
        help="Where to write the review report. Default: <output>.proofread.json",
    )

    proofread.add_argument(
        "--proofread-dry-run",
        action="store_true",
        help="Review and write the report, but do not change the subtitles",
    )

    proofread.add_argument(
        "--proofread-backend",
        type=str,
        choices=["gemini", "fake"],
        default="gemini",
        help=argparse.SUPPRESS,
    )

    proofread.add_argument(
        "--proofread-fake-patches",
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )

    return parser


BUILTIN_TRANSLATORS: dict[str, type[Translator]] = {
    "deepl-scrap": DeeplTranslator,
    "deepl-api": DeeplApi,
    "translatepy": TranslatePy,
    "pydeeplx": PyDeepLX,
}


def configure_logging(level: int | None) -> None:
    logging.basicConfig(level=level or logging.WARNING, format="%(message)s")


def configure_headless(show_browser: bool) -> None:
    if show_browser:
        os.environ.pop("MOZ_HEADLESS", None)
        return
    os.environ["MOZ_HEADLESS"] = "1"


def load_subtitle(filepath: str, **srt_options):
    try:
        return AssFile(filepath)
    except AttributeError:
        LOG.info("Falling back to SRT parsing")
        return SrtFile(filepath, **srt_options)


def is_finnish(lang: str) -> bool:
    return (lang or "").strip().lower().split("-")[0] in ("fi", "fin", "finnish")


#: Arguments for sisusub's fix-finnish-subs, the same house style exsubs uses.
#: Its own AI review stays off: the Gemini proof-read has already run.
FIXER_ARGS = ["--no-ai-review", "--width-limit", "42", "--max-cps", "17", "--cps-target", "15"]


def proofread_enabled(args: argparse.Namespace) -> bool:
    """Whether to review this run.

    Explicit flags win. With neither, the stage turns itself on only when it can
    actually run, so an install without the extra behaves exactly as before.
    """
    if args.proofread is not None:
        return bool(args.proofread)
    if args.proofread_backend == "fake":
        return False
    return gemini_backend.sdk_available() and gemini_backend.credentials_available()


def build_proofread_options(args: argparse.Namespace, report_for: str) -> ProofreadOptions:
    return ProofreadOptions(
        model=args.proofread_model or gemini_backend.default_model(),
        thinking_level=args.proofread_thinking or gemini_backend.default_thinking_level(),
        min_severity=args.proofread_min_severity,
        max_change_fraction=args.proofread_max_change,
        target_cps=args.target_cps,
        max_cost_usd=args.proofread_max_cost,
        dry_run=args.proofread_dry_run,
        report_path=args.proofread_report,
        wrap_limit=args.wrap_limit,
        max_lines=args.max_lines,
    )


def build_proofread_backend(args: argparse.Namespace, options: ProofreadOptions):
    """The reviewing model, or None when the run may proceed without one."""
    if args.proofread_backend == "fake":
        from .proofread.backends.fake import FakeBackend

        if args.proofread_fake_patches:
            return FakeBackend.from_file(args.proofread_fake_patches)
        return FakeBackend([])

    try:
        return gemini_backend.GeminiBackend.from_env(
            model=options.model, thinking_level=options.thinking_level
        )
    except ProofreadError as error:
        if args.proofread:
            raise
        LOG.warning("Skipping proof-reading: %s", error)
        return None


def run_pipeline_proofread(args: argparse.Namespace, sub: SrtFile, dest_path: str) -> bool:
    """Review the translation in place, never letting a failure lose it.

    The translation has already been paid for by the time this runs, and an
    exception escaping here would reach main()'s handler, which truncates the file
    to a .tmp backup. Everything is caught, including the filesystem and SDK errors
    that are not ProofreadError: a report that cannot be written, or a client that
    cannot authenticate, must not cost the user their translation.

    Returns False when the review could not run or ended in an error, so main()
    can exit non-zero for an explicit --proofread after saving the translation.
    """
    options = build_proofread_options(args, dest_path)
    try:
        backend = build_proofread_backend(args, options)
    except Exception as error:  # noqa: BLE001 - see the docstring
        LOG.error("Proof-reading unavailable: %s", error)
        return False
    if backend is None:
        return False

    try:
        result = proofread_srt_file(
            sub, backend, options, args.src_lang, args.dest_lang, report_for=dest_path
        )
    except Exception as error:  # noqa: BLE001 - see the docstring
        LOG.error("Proof-reading failed: %s", error)
        LOG.debug(traceback.format_exc())
        return False

    print(result.summary())
    if result.report_path:
        LOG.info("Proof-reading report: %s", result.report_path)
    return result.status != "error"


def run_proofread_only(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Review an already translated file against its original."""
    if not args.source:
        parser.error("--proofread-only needs --source pointing at the original subtitle")
    if not os.path.exists(args.source):
        parser.error(f"Source file not found: {args.source}")
    if not os.path.exists(args.filepath):
        parser.error(f"Translated file not found: {args.filepath}")

    options = build_proofread_options(args, args.filepath)
    try:
        backend = build_proofread_backend(args, options)
    except Exception as error:  # noqa: BLE001 - a CLI reports, it does not traceback
        LOG.error("%s", error)
        return 1
    if backend is None:
        LOG.error("Proof-reading is not available in this environment")
        return 1

    try:
        result = proofread_pair(
            args.source,
            args.filepath,
            backend,
            options,
            args.src_lang,
            args.dest_lang,
        )
    except ProofreadError as error:
        # Ordinary user errors, including ProofreadAlignmentError when the two
        # files do not describe the same cues.
        LOG.error("%s", error)
        return 1
    except OSError as error:
        LOG.error("Could not read or write a subtitle file: %s", error)
        return 1
    except Exception as error:  # noqa: BLE001 - a CLI reports, it does not traceback
        LOG.error("Proof-reading failed: %s", error)
        LOG.debug(traceback.format_exc())
        return 1

    print(result.summary())
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.status == "applied" and result.applied:
        print(
            "Mechanical fixes were not re-run. If this file has not been through "
            "fix-finnish-subs yet, run it once now."
        )
    return 0 if result.status in ("applied", "dry_run") else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if sys.platform.startswith("win"):
        parser.error("SRTranslator CLI supports Linux and macOS only.")

    configure_logging(args.loglevel)
    configure_headless(args.show_browser)

    if args.proofread_only:
        # Before the translator is constructed: this path never translates, and
        # deepl-api would demand an API key it is not going to use.
        return run_proofread_only(args, parser)

    if args.source:
        parser.error("--source is only used with --proofread-only")

    translator_args = {}
    if args.auth:
        translator_args["api_key"] = args.auth
    elif args.translator == "deepl-api":
        api_key = os.environ.get("DEEPL_API_KEY", "").strip()
        if not api_key:
            parser.error("deepl-api needs --auth or the DEEPL_API_KEY environment variable")
        translator_args["api_key"] = api_key

    if args.translator == "pydeeplx" and args.proxies:
        translator_args["proxies"] = args.proxies

    instructions = list(args.custom_instructions or [])
    if args.instruction_preset:
        try:
            instructions = instruction_preset(args.instruction_preset) + instructions
        except ValueError as error:
            parser.error(str(error))

    if args.translator == "deepl-api":
        if args.context:
            translator_args["context"] = args.context
        translator_args["model_type"] = args.model_type
        if instructions:
            if len(instructions) > 10:
                parser.error("At most 10 custom instructions, including the preset")
            translator_args["custom_instructions"] = instructions
        if args.glossary_id:
            translator_args["glossary_id"] = args.glossary_id
    elif instructions or args.glossary_id:
        parser.error(
            "--instruction, --instruction-preset and --glossary-id need the deepl-api translator"
        )

    try:
        translator = BUILTIN_TRANSLATORS[args.translator](**translator_args)
    except ValueError as error:
        parser.error(str(error))
    sub = None
    try:
        sub = load_subtitle(
            args.filepath,
            # Only DeepL's XML tag handling carries <i> through a translation.
            keep_italics=args.translator == "deepl-api",
            filter_sdh=args.filter_sdh,
            merge_fragments=args.merge_fragments,
        )

        sub.translate(translator, args.src_lang, args.dest_lang)

        dest_path = args.output or (
            f"{os.path.splitext(args.filepath)[0]}_{args.dest_lang}"
            f"{os.path.splitext(args.filepath)[1]}"
        )

        # Proof-read before wrapping: the cue text is still one line per cue and
        # the source text is still available, so meaning is corrected first and
        # layout is decided afterwards from the final text.
        proofread_ok = True
        if proofread_enabled(args):
            if isinstance(sub, SrtFile):
                proofread_ok = run_pipeline_proofread(args, sub, dest_path)
            else:
                LOG.warning("Proof-reading supports .srt files only, skipping")

        # Use postprocess API for SrtFile, fallback to wrap_lines for AssFile
        if isinstance(sub, SrtFile):
            result = sub.postprocess(
                target_language=args.dest_lang,
                use_cps_wrapping=args.use_cps,
                target_cps=args.target_cps,
                line_wrap_limit=args.wrap_limit,
                max_lines=args.max_lines,
                validate_output=args.validate,
                check_formality=not args.no_formality_check,
            )

            # Print warnings if validation was requested
            if args.validate and result["warnings"]:
                sub.print_warnings(
                    target_cps=args.target_cps,
                    check_formality=not args.no_formality_check,
                    target_language=args.dest_lang,
                )
        else:
            sub.wrap_lines(args.wrap_limit)

        sub.save(dest_path)
        LOG.info("Translation completed. Saved to %s", dest_path)

        # Run fix-finnish-subs on a Finnish translation (unless disabled). Its
        # rules are Finnish rules, so it never touches another language.
        if not args.no_external_fixer and isinstance(sub, SrtFile) and is_finnish(args.dest_lang):
            fixer_result = sub.run_external_fixer(
                dest_path,
                command="fix-finnish-subs",
                args=[*FIXER_ARGS, "--report", f"{dest_path}.fixer-report.txt"],
            )
            if fixer_result["success"]:
                LOG.info("fix-finnish-subs completed successfully")
                if fixer_result.get("stdout"):
                    LOG.debug("fix-finnish-subs output: %s", fixer_result["stdout"])
            elif "not found" in fixer_result.get("error", ""):
                LOG.warning("fix-finnish-subs command not found. Skipping post-processing.")
            else:
                LOG.error(
                    "fix-finnish-subs failed with exit code %d", fixer_result.get("returncode", -1)
                )
                if fixer_result.get("stderr"):
                    LOG.error("Error output: %s", fixer_result["stderr"])
                LOG.warning("Translation was saved but post-processing failed")

        if args.proofread and not proofread_ok:
            # Saved, but the review that was explicitly required did not happen.
            LOG.error("Proof-reading was required (--proofread) but did not complete")
            return 3
        return 0
    except Exception:
        if sub:
            sub.save_backup()
            LOG.error("Translation failed. Backup saved to %s", sub.backup_file)
        else:
            LOG.error("Translation failed before processing the subtitle file.")
        LOG.debug(traceback.format_exc())
        return 1
    finally:
        translator.quit()


if __name__ == "__main__":
    sys.exit(main())
