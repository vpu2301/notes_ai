"""Audacity label track (``start<TAB>end<TAB>label``, seconds) to RTTM.

uv run python scripts/eval/labels_to_rttm.py FILE_ID labels.txt > eval/speakers/v1/rttm/FILE_ID.rttm
"""

from __future__ import annotations

import sys
from pathlib import Path


def convert(file_id: str, text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        parts = raw.strip().split("\t")
        if len(parts) < 3 or parts[0].startswith("\\"):
            continue  # blank lines and spectral-selection rows ("\\ …")
        start, end, label = float(parts[0]), float(parts[1]), parts[2].strip()
        if end <= start or not label:
            continue
        lines.append(
            f"SPEAKER {file_id} 1 {start:.3f} {end - start:.3f} <NA> <NA> {label} <NA> <NA>"
        )
    return sorted(lines, key=lambda line: float(line.split()[3]))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    text = "\n".join(Path(p).read_text() for p in sys.argv[2:])
    print("\n".join(convert(sys.argv[1], text)))
