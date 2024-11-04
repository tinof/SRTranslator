import deepl
from typing import Optional
from .base import Translator, TranslationError


class DeepLApi(Translator):
    """
    Handles translation using DeepL API with context support
    """
    max_char = 1500  # DeepL's default limit, can be adjusted based on your plan

    def __init__(self, api_key: str, source_lang: Optional[str] = None):
        self.translator = deepl.Translator(api_key)
        self.source_lang = source_lang
        self._context_window = []
        self.max_context_length = 240  # DeepL has 128 KiB request limit

    def _build_context(self, text: str) -> str:
        """Build context from previous translations"""
        # Keep last few translations as context
        self._context_window.append(text)
        if len(self._context_window) > 3:  # Keep last 3 translations
            self._context_window.pop(0)
        
        # Format context
        context = " ".join(self._context_window[:-1])  # Exclude current text
        return context[:self.max_context_length]

    def translate(self, text: str, source_language: str, destination_language: str) -> str:
        """
        Translate text using DeepL API with context support
        """
        try:
            # Build context from previous translations
            context = self._build_context(text)

            # Make DeepL API call with context
            result = self.translator.translate_text(
                text=text,
                source_lang=source_language if source_language != "auto" else None,
                target_lang=destination_language,
                context=context,
                split_sentences="nonewlines",  # Preserve subtitle line breaks
                tag_handling="xml" if "<" in text else None
            )

            return result.text

        except deepl.DeepLException as e:
            raise TranslationError(f"DeepL translation failed: {str(e)}")
