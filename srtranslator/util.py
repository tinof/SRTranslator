import re
import sys


def show_progress(total: int, progress: int):
    """Displays or updates a console progress bar"""

    barLength, status = 20, ""
    progress = float(progress) / float(total)
    if progress >= 1.0:
        progress, status = 1, "\r\n"
    block = int(round(barLength * progress))
    text = "\r[{}] {:.0f}% {}".format(
        "#" * block + "-" * (barLength - block), round(progress * 100, 0), status
    )
    sys.stdout.write(text)
    sys.stdout.flush()


# DeepL rejects a request body over 128 KiB. Stay clear of the edge, because a
# chunk is measured in characters while the body is measured in bytes.
MAX_REQUEST_BODY_BYTES = 120_000


def fit_context(context: str | None, text: list[str]) -> str | None:
    """Trim context so the translation request body stays under the limit.

    The lines nearest the chunk carry the most meaning and are appended last, so
    the tail is kept and the head is dropped.
    """
    if not context:
        return context

    budget = MAX_REQUEST_BODY_BYTES - sum(len(line.encode("utf-8")) for line in text)
    if budget <= 0:
        return None

    encoded = context.encode("utf-8")
    if len(encoded) <= budget:
        return context

    trimmed = encoded[-budget:].decode("utf-8", errors="ignore")
    # Drop the leading partial line left by the byte-wise cut
    return trimmed.split("\n", 1)[-1] or None


def clean_context_line(text: str) -> str:
    """Strip subtitle placeholders so a context line reads as plain dialogue.

    The ASS class encodes dialog markers as ``////`` and line breaks as runs of
    backslashes. Those mean nothing to a translation engine. Only the context
    copy is cleaned; the text sent for translation keeps its placeholders.
    """
    text = text.replace("////", " ")
    text = re.sub(r"\\+N", " ", text)
    text = re.sub(r"\\+", " ", text)
    return " ".join(text.split())
