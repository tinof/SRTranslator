import os
import deepl
from typing import Optional, List
from .base import Translator, TranslationError


class DeepLApi(Translator):
    """
    DeepL API translator implementation with context support
    """
    def __init__(self, api_key: str, source_lang: Optional[str] = None):
        """
        Initialize DeepL translator
        
        Args:
            api_key: DeepL API authentication key
            source_lang: Optional source language code
        """
        self.api_key = api_key
        self.source_lang = source_lang
        self._context_window: List[str] = []
        self.max_context_length = 240
        
        try:
            self.translator = deepl.Translator(api_key)
            # Validate API key by checking usage
            self.translator.get_usage()
        except deepl.exceptions.AuthorizationException:
            raise TranslationError("DeepL API key authentication failed")
        except Exception as e:
            raise TranslationError(f"Failed to initialize DeepL translator: {str(e)}")

    @property
    def supported_languages(self) -> List[str]:
        """Get list of supported language codes"""
        try:
            source_langs = self.translator.get_source_languages()
            target_langs = self.translator.get_target_languages()
            return list(set([l.code.lower() for l in source_langs + target_langs]))
        except Exception as e:
            raise TranslationError(f"Failed to get supported languages: {str(e)}")

    def translate(self, text: str, source_language: str, destination_language: str) -> str:
        """
        Translate text using DeepL API
        
        Args:
            text: Text to translate
            source_language: Source language code
            destination_language: Target language code
            
        Returns:
            Translated text
        """
        if not text or not text.strip():
            return text

        try:
            # Map language codes to DeepL format
            source_lang = self._map_language_code(source_language) if source_language != "auto" else None
            target_lang = self._map_language_code(destination_language)
            
            # Build context from previous translations
            context = self._build_context(text)

            # Perform translation
            result = self.translator.translate_text(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                context=context,
                split_sentences="nonewlines",
                tag_handling="xml" if "<" in text else None,
                preserve_formatting=True
            )

            # Update context window
            self._update_context(text)

            return result.text

        except deepl.exceptions.AuthorizationException:
            raise TranslationError("DeepL API authentication failed")
        except deepl.exceptions.QuotaExceededException:
            raise TranslationError("DeepL API quota exceeded")
        except deepl.exceptions.TooManyRequestsException:
            raise TranslationError("Too many requests to DeepL API")
        except deepl.DeepLException as e:
            raise TranslationError(f"DeepL translation error: {str(e)}")
        except Exception as e:
            raise TranslationError(f"Translation failed: {str(e)}")

    def _build_context(self, current_text: str) -> str:
        """Build context string from previous translations"""
        if not self._context_window:
            return ""
            
        context = " ".join(self._context_window)
        return context[:self.max_context_length]

    def _update_context(self, text: str):
        """Update context window with new text"""
        self._context_window.append(text)
        if len(self._context_window) > 3:  # Keep last 3 translations
            self._context_window.pop(0)

    def _map_language_code(self, lang_code: str) -> str:
        """
        Map language codes to DeepL supported formats
        """
        # DeepL language code mapping
        mapping = {
            # Add mappings as needed
            'en': 'EN-US',  # or 'EN-GB'
            'pt': 'PT-PT',  # or 'PT-BR'
            'zh': 'ZH',     # Simplified Chinese
            # Add more mappings as needed
        }
        return mapping.get(lang_code.lower(), lang_code.upper())

    def quit(self):
        """Cleanup method"""
        pass  # No cleanup needed for DeepL API
