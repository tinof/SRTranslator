import textwrap

import pytest

SOURCE_SRT = """
1
00:00:00,000 --> 00:00:02,000
I saw her leave the bank.

2
00:00:02,500 --> 00:00:04,500
-Are you sure?
-Quite sure.

3
00:00:10,000 --> 00:00:13,000
She took the case with her.

4
00:00:13,500 --> 00:00:16,000
Then we have nothing.
"""

TRANSLATED_SRT = """
1
00:00:00,000 --> 00:00:02,000
Näin hänen lähtevän penkiltä.

2
00:00:02,500 --> 00:00:04,500
-Oletko varma?
-Aivan varma.

3
00:00:10,000 --> 00:00:13,000
Hän otti laukun mukaansa.

4
00:00:13,500 --> 00:00:16,000
Sitten meillä ei ole mitään.
"""


def _write_srt(path, content: str) -> str:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def write_srt():
    """Write a dedented SRT to a path and return the path as a string."""
    return _write_srt


@pytest.fixture
def source_path(tmp_path):
    return _write_srt(tmp_path / "movie.srt", SOURCE_SRT)


@pytest.fixture
def translated_path(tmp_path):
    return _write_srt(tmp_path / "movie_fi.srt", TRANSLATED_SRT)
