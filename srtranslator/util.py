import json
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


# DeepL rejects a request body over 128 KiB. Stay clear of the edge.
MAX_REQUEST_BODY_BYTES = 120_000

# Headroom for the other fields the translator adds to the same body: the global
# context, custom instructions, language codes and the option flags.
REQUEST_OVERHEAD_BYTES = 8_000


def _wire_len(value: str) -> int:
    """Length of a string as the DeepL client actually sends it.

    The client posts JSON through requests, which serialises with
    ensure_ascii=True. Non-ASCII expands to \\uXXXX escapes and backslashes are
    doubled, so a CJK context goes on the wire at roughly twice its UTF-8 size.
    Measuring UTF-8 bytes here would under-count by half.
    """
    return len(json.dumps(value))


def fit_context(context: str | None, text: list[str]) -> str | None:
    """Trim context so the translation request body stays under the limit.

    This is a backstop. The context budgets in the subtitle classes keep the
    string far below the limit, so under current settings it never trims. Whole
    lines are dropped from the head, because the lines nearest the chunk carry
    the most meaning and are appended last.
    """
    if not context:
        return context

    budget = MAX_REQUEST_BODY_BYTES - REQUEST_OVERHEAD_BYTES
    budget -= sum(_wire_len(line) for line in text)
    if budget <= 0:
        return None

    # Walk from the tail and keep as many whole lines as fit. Costing each line
    # separately over-counts slightly, which is the safe direction for a backstop.
    kept = []
    used = 0
    for line in reversed(context.split("\n")):
        cost = _wire_len(line) + 1  # +1 for the newline that rejoins it
        if used + cost > budget:
            break
        kept.append(line)
        used += cost

    kept.reverse()
    return "\n".join(kept) or None


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
