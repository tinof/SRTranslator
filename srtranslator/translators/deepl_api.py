import logging

import deepl

from .base import Translator

LOG = logging.getLogger("srtranslator")

# Target languages DeepL accepts for the custom_instructions parameter.
# Compared against the base language code, so "en-GB" matches "en".
CUSTOM_INSTRUCTION_LANGUAGES = frozenset({"de", "en", "es", "fr", "it", "ja", "ko", "zh"})

MAX_CUSTOM_INSTRUCTIONS = 10
MAX_CUSTOM_INSTRUCTION_CHARS = 300


class DeeplApi(Translator):
    max_char = 1500

    def __init__(
        self,
        api_key,
        context=None,
        model_type="quality_optimized",
        preserve_formatting=True,
        tag_handling="xml",
        split_sentences="nonewlines",
        custom_instructions: list[str] | None = None,
    ):
        if custom_instructions and model_type == "latency_optimized":
            raise ValueError(
                "DeepL rejects custom instructions together with the latency_optimized "
                "model. Use quality_optimized, or drop the instructions."
            )

        if custom_instructions:
            if len(custom_instructions) > MAX_CUSTOM_INSTRUCTIONS:
                raise ValueError(
                    f"DeepL accepts at most {MAX_CUSTOM_INSTRUCTIONS} custom instructions, "
                    f"got {len(custom_instructions)}."
                )
            if any(len(i) > MAX_CUSTOM_INSTRUCTION_CHARS for i in custom_instructions):
                raise ValueError(
                    "Each DeepL custom instruction is limited to "
                    f"{MAX_CUSTOM_INSTRUCTION_CHARS} characters."
                )

        self.translator = deepl.DeepLClient(api_key)
        self.context = context
        self.model_type = model_type
        self.preserve_formatting = preserve_formatting
        self.tag_handling = tag_handling
        self.split_sentences = split_sentences
        self.custom_instructions = custom_instructions
        self.billed_characters = 0
        self.logged_model_type = False  # Only log once
        self._warned_instructions = False

    def _instructions_supported(self, destination_language: str) -> bool:
        return destination_language.split("-")[0].lower() in CUSTOM_INSTRUCTION_LANGUAGES

    def _request_kwargs(
        self,
        source_language: str | None,
        destination_language: str,
        context: str | None,
    ) -> dict:
        """Build the keyword arguments for one translate_text call."""
        kwargs = {
            # DeepL expects no source_lang at all for auto detection
            "source_lang": None
            if not source_language or source_language.lower() == "auto"
            else source_language,
            "target_lang": destination_language,
            "model_type": self.model_type,
        }

        # Combine global context and dynamic context
        combined_context = [c for c in (self.context, context) if c]
        if combined_context:
            kwargs["context"] = "\n\n".join(combined_context)

        # Formatting and tag handling options
        if self.preserve_formatting:
            kwargs["preserve_formatting"] = self.preserve_formatting
        if self.tag_handling:
            kwargs["tag_handling"] = self.tag_handling
        if self.split_sentences:
            kwargs["split_sentences"] = self.split_sentences

        if self.custom_instructions:
            if self._instructions_supported(destination_language):
                kwargs["custom_instructions"] = self.custom_instructions
            elif not self._warned_instructions:
                self._warned_instructions = True
                LOG.warning(
                    "DeepL custom instructions are not supported for target language %s. "
                    "Continuing without them. Supported: %s.",
                    destination_language,
                    ", ".join(sorted(CUSTOM_INSTRUCTION_LANGUAGES)),
                )

        return kwargs

    def _record_result(self, result) -> None:
        """Accumulate billing and log the model actually used, once."""
        billed = getattr(result, "billed_characters", None)
        if billed:
            self.billed_characters += billed

        if not self.logged_model_type:
            model_used = getattr(result, "model_type_used", None)
            if model_used:
                self.logged_model_type = True
                LOG.info("DeepL model used: %s", model_used)

    def translate_single(
        self,
        text: str,
        source_language: str,
        destination_language: str,
        context: str | None = None,
    ):
        result = self.translator.translate_text(
            text,
            **self._request_kwargs(source_language, destination_language, context),
        )
        self._record_result(result)
        return result.text

    def translate_batch(
        self,
        text: list,
        source_language: str,
        destination_language: str,
        context: str | None = None,
    ):
        # DeepL API handles a list of strings natively
        results = self.translator.translate_text(
            text,
            **self._request_kwargs(source_language, destination_language, context),
        )

        for result in results:
            self._record_result(result)

        # results is a list of TextResult objects
        return [result.text for result in results]

    def quit(self) -> None:
        if self.billed_characters:
            LOG.info("DeepL billed characters: %d", self.billed_characters)
