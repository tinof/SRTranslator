from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback

from .ass_file import AssFile
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
        help="API key if needed by the translator",
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
        choices=["latency_optimized", "quality_optimized", "prefer_quality_optimized"],
        help="Model type for DeepL translation (only for deepl-api)",
    )

    parser.add_argument(
        "--no-external-fixer",
        action="store_true",
        help="Disable running fix-finnish-subs after translation",
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


def load_subtitle(filepath: str):
    try:
        return AssFile(filepath)
    except AttributeError:
        LOG.info("Falling back to SRT parsing")
        return SrtFile(filepath)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if sys.platform.startswith("win"):
        parser.error("SRTranslator CLI supports Linux and macOS only.")

    configure_logging(args.loglevel)
    configure_headless(args.show_browser)

    translator_args = {}
    if args.auth:
        translator_args["api_key"] = args.auth

    if args.translator == "pydeeplx" and args.proxies:
        translator_args["proxies"] = args.proxies

    if args.translator == "deepl-api":
        if args.context:
            translator_args["context"] = args.context
        if args.model_type:
            translator_args["model_type"] = args.model_type

    translator = BUILTIN_TRANSLATORS[args.translator](**translator_args)
    sub = None
    try:
        sub = load_subtitle(args.filepath)

        sub.translate(translator, args.src_lang, args.dest_lang)

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

        dest_path = (
            f"{os.path.splitext(args.filepath)[0]}_{args.dest_lang}"
            f"{os.path.splitext(args.filepath)[1]}"
        )
        sub.save(dest_path)
        LOG.info("Translation completed. Saved to %s", dest_path)

        # Run fix-finnish-subs on the translated file (unless disabled)
        if not args.no_external_fixer and isinstance(sub, SrtFile):
            fixer_result = sub.run_external_fixer(
                dest_path,
                command="fix-finnish-subs",
                args=["--no-ai-review"],
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
