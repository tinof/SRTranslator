import deepl
from .base import Translator


class DeeplApi(Translator):
    max_char = 1500

    def __init__(self, api_key, context=None, model_type=None):
        self.translator = deepl.Translator(api_key)
        self.context = context
        self.model_type = model_type
        self.logged_model_type = False  # Only log once

    def translate_single(
        self,
        text: str,
        source_language: str,
        destination_language: str,
        context: str = None,
    ):
        # DeepL API supports single string or list.
        # But translate_single expects a single string input and output.
        kwargs = {}

        # Combine global context and dynamic context
        combined_context = []
        if self.context:
            combined_context.append(self.context)
        if context:
            combined_context.append(context)

        if combined_context:
            kwargs["context"] = " ".join(combined_context)

        if self.model_type:
            kwargs["model_type"] = self.model_type

        result = self.translator.translate_text(
            text,
            source_lang=source_language,
            target_lang=destination_language,
            **kwargs,
        )

        # Log which model was actually used (only once)
        if not self.logged_model_type and hasattr(result, "model_type_used"):
            print(f"DeepL model used: {result.model_type_used}")
            self.logged_model_type = True

        return result.text

    def translate_batch(
        self,
        text: list,
        source_language: str,
        destination_language: str,
        context: str = None,
    ):
        kwargs = {}

        # Combine global context and dynamic context
        combined_context = []
        if self.context:
            combined_context.append(self.context)
        if context:
            combined_context.append(context)

        if combined_context:
            kwargs["context"] = " ".join(combined_context)

        if self.model_type:
            kwargs["model_type"] = self.model_type

        # DeepL API handles list of strings natively
        results = self.translator.translate_text(
            text,
            source_lang=source_language,
            target_lang=destination_language,
            **kwargs,
        )

        # Log which model was actually used (only once)
        if (
            not self.logged_model_type
            and len(results) > 0
            and hasattr(results[0], "model_type_used")
        ):
            print(f"DeepL model used: {results[0].model_type_used}")
            self.logged_model_type = True

        # results is a list of TextResult objects
        return [r.text for r in results]
