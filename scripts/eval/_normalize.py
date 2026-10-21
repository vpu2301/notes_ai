"""One normaliser for every scorer (A1/A2 review, step 2). Since Sprint R0 the
implementation lives in ``note_service.domain.text`` (the item writer reads the same
rules); this module keeps the scorers' import path.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE_SRC = Path(__file__).resolve().parents[2] / "services" / "note-service" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

from note_service.domain.text import (  # noqa: E402
    FOLD_COMPOUND_MIN as COMPOUND_MIN,
)
from note_service.domain.text import (  # noqa: E402
    NORMALIZER_VERSION,
    _holder_pattern,
    _plain,
    _token_matches,
    contains,
    fold,
)

__all__ = [
    "COMPOUND_MIN",
    "NORMALIZER_VERSION",
    "_holder_pattern",
    "_plain",
    "_token_matches",
    "contains",
    "fold",
]
