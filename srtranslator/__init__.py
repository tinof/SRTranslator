import os

from .ass_file import AssFile
from .srt_file import SrtFile

os.environ["MOZ_HEADLESS"] = "1"

__all__ = ["AssFile", "SrtFile"]
