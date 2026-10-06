from abc import ABC, abstractmethod


class Translator(ABC):
    max_char: int
    #: Most cues one request may carry, or None for no limit beyond max_char.
    max_items: int | None = None

    def translate(
        self,
        text: str,
        source_language: str,
        destination_language: str,
        context: str = None,
    ) -> str:
        if isinstance(text, list):
            return self.translate_batch(text, source_language, destination_language, context)
        return self.translate_single(text, source_language, destination_language, context)

    def translate_batch(
        self,
        text: list,
        source_language: str,
        destination_language: str,
        context: str = None,
    ) -> list:
        # Default implementation: join and split
        joined = "\n".join(text)
        result = self.translate_single(joined, source_language, destination_language, context)
        return result.splitlines()

    @abstractmethod
    def translate_single(
        self,
        text: str,
        source_language: str,
        destination_language: str,
        context: str = None,
    ) -> str: ...

    def quit(self):
        """Cleanup resources. Subclasses can override."""
        pass


class TimeOutException(Exception):
    """Translation timed out"""
