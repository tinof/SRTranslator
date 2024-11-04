import os
from argparse import ArgumentParser
from dotenv import load_dotenv
from typing import Optional

from .translators import (
    DeepLApi,      # Official DeepL API
    DeeplTranslator,  # DeepL web scraper
    TranslatePy,   # Multiple translation services
    PyDeepLX      # Unofficial DeepL
)
from .srt_file import SrtFile

# Load environment variables from .env file
load_dotenv()

def get_translator(args) -> Optional[TranslationService]:
    """
    Get appropriate translator instance based on arguments
    
    Args:
        args: Command line arguments

    Returns:
        Initialized translator instance
        
    Raises:
        ValueError: If translator type is invalid or required API key is missing
    """
    if args.translator == "deepl-api":
        # Official DeepL API
        api_key = args.auth or os.getenv('DEEPL_API_KEY')
        if not api_key:
            raise ValueError(
                "DeepL API key required. Provide with --auth or set DEEPL_API_KEY environment variable"
            )
        return DeepLApi(api_key=api_key)
    
    elif args.translator == "deepl-scrap":
        # Web scraping version of DeepL (no API key needed)
        return DeeplTranslator()
    
    elif args.translator == "translatepy":
        # TranslatePy supports multiple services
        return TranslatePy()
    
    elif args.translator == "pydeeplx":
        # Unofficial DeepL implementation
        if args.auth:
            return PyDeepLX(api_key=args.auth)
        return PyDeepLX()
    
    else:
        raise ValueError(f"Unknown translator: {args.translator}")

def main():
    parser = ArgumentParser(description="Translate subtitles using various services")
    
    # Required arguments
    parser.add_argument(
        "filepath",
        help="Path to subtitle file"
    )
    
    # Translator selection
    parser.add_argument(
        "-t",
        "--translator",
        type=str,
        choices=["deepl-scrap", "translatepy", "deepl-api", "pydeeplx"],
        help="Translation service to use",
        default="deepl-scrap"
    )
    
    # Authentication
    parser.add_argument(
        "--auth",
        type=str,
        help="API key for translation service (required for deepl-api, optional for pydeeplx)"
    )
    
    # Language options
    parser.add_argument(
        "-i",
        "--src_lang",
        type=str,
        help="Source language code (default: auto-detect)",
        default="auto"
    )
    parser.add_argument(
        "-o",
        "--dest_lang",
        type=str,
        help="Destination language code",
        required=True
    )
    
    # Additional options
    parser.add_argument(
        "--timeout",
        type=int,
        help="Timeout in seconds for translation requests",
        default=30
    )
    parser.add_argument(
        "--retries",
        type=int,
        help="Number of retries for failed translations",
        default=3
    )
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay between translation requests in seconds",
        default=0.0
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: input_translated.srt)",
        default=None
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    try:
        # Initialize selected translator
        translator = get_translator(args)
        
        # Load subtitle file
        sub = SrtFile(args.filepath)
        
        if args.verbose:
            print(f"Translating {args.filepath}")
            print(f"From: {args.src_lang}")
            print(f"To: {args.dest_lang}")
            print(f"Using: {args.translator}")
        
        # Perform translation
        sub.translate(
            translator,
            args.src_lang,
            args.dest_lang,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay
        )
        
        # Save translated subtitles
        if args.output:
            sub.save(args.output)
        else:
            sub.save()
            
        if args.verbose:
            print("Translation completed successfully")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)
    finally:
        if translator:
            translator.quit()

if __name__ == "__main__":
    main()
