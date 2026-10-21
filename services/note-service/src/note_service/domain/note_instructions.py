"""Note instructions (N1, N4): how a workspace, a meeting type or one note wants its
notes written. The text is stored and shown; nothing compiles it (Sprint R0) — the
writer (P1) reads it as written. Configuration treated as content: never in a log
line, an audit payload, a metric label or an error detail.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Final

MAX_CHARS: Final = 8000

# What the stored rows carry in the columns the compiler used to fill (R0: no
# compiler; the columns are NOT NULL, so they hold the empty values).
STORED_PROFILE: Final[dict[str, Any]] = {}
STORED_PROFILE_HASH: Final = ""
STORED_COMPILE_STATUS: Final = "compiled"
STORED_COMPILER_VERSION: Final = "none"

_DELIMITERS: Final = re.compile("[⟦⟧]")
# C0 and C1 controls except \t and \n.
_CONTROLS: Final = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BLANK_LINES: Final = re.compile(r"\n{3,}")


def sanitize_text(text: str, *, max_chars: int = MAX_CHARS) -> str:
    """NFC, no ⟦ ⟧, no control characters (tabs and newlines kept), at most one blank line
    in a row, trimmed. Longer than ``max_chars`` is the caller's 413, never a silent cut;
    this only caps what it is handed when the caller chose to."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROLS.sub("", _DELIMITERS.sub("", text))
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text[:max_chars] if len(text) > max_chars else text
