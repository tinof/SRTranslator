from translatepy import Translator

from .base import Translator as BaseTranslator


class TranslatePy(BaseTranslator):
    max_char = 1e10

    def __init__(self):
        self.translator = Translator()

    def translate_single(
        self, text, source_language, destination_language, context=None
    ):
        result = self.translator.translate(
            text,
            source_language=source_language,
            destination_language=destination_language,
        )
        return result.result
