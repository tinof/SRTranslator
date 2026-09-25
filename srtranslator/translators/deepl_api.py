import logging
import re
from xml.sax.saxutils import unescape

import deepl

from .base import Translator

LOG = logging.getLogger("srtranslator")

# Verified against the live API: DeepL enforces both of these and returns a clear
# Bad request when either is exceeded, so failing fast here saves a round trip.
# It does NOT restrict custom_instructions by target language, and it does NOT
# reject them with latency_optimized, so this class imposes neither.
MAX_CUSTOM_INSTRUCTIONS = 10
MAX_CUSTOM_INSTRUCTION_CHARS = 300

# With tag_handling="xml" DeepL parses every text AND the context as XML, and one
# stray "&" or "<" fails the whole request ("Tag handling parsing failed"). Only
# XML's predefined and numeric entities survive as-is: an HTML entity such as
# &nbsp; is undefined in XML, so its "&" is escaped too and round-trips as text.
_BARE_AMPERSAND = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
# A "<" that does not open or close a tag, such as "3 < 5" or "<<".
_BARE_LESS_THAN = re.compile(r"<(?!/?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>)")
_XML_UNESCAPES = {"&quot;": '"', "&apos;": "'"}


def xml_escape_text(text: str) -> str:
    """Escape the characters that would make subtitle text invalid XML, keeping tags."""
    return _BARE_LESS_THAN.sub("&lt;", _BARE_AMPERSAND.sub("&amp;", text))


def xml_unescape_text(text: str) -> str:
    """Undo the entities DeepL returns in XML mode (it also escapes a plain ">")."""
    return unescape(text, _XML_UNESCAPES)


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
            kwargs["context"] = self._to_request_text("\n\n".join(combined_context))

        # Formatting and tag handling options
        if self.preserve_formatting:
            kwargs["preserve_formatting"] = self.preserve_formatting
        if self.tag_handling:
            kwargs["tag_handling"] = self.tag_handling
        if self.split_sentences:
            kwargs["split_sentences"] = self.split_sentences

        if self.custom_instructions:
            kwargs["custom_instructions"] = self.custom_instructions

        return kwargs

    def _to_request_text(self, text: str) -> str:
        return xml_escape_text(text) if self.tag_handling == "xml" else text

    def _from_result_text(self, text: str) -> str:
        return xml_unescape_text(text) if self.tag_handling == "xml" else text

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
            self._to_request_text(text),
            **self._request_kwargs(source_language, destination_language, context),
        )
        self._record_result(result)
        return self._from_result_text(result.text)

    def translate_batch(
        self,
        text: list,
        source_language: str,
        destination_language: str,
        context: str | None = None,
    ):
        # DeepL API handles a list of strings natively
        results = self.translator.translate_text(
            [self._to_request_text(item) for item in text],
            **self._request_kwargs(source_language, destination_language, context),
        )

        for result in results:
            self._record_result(result)

        # results is a list of TextResult objects
        return [self._from_result_text(result.text) for result in results]

    def quit(self) -> None:
        if self.billed_characters:
            LOG.info("DeepL billed characters: %d", self.billed_characters)
