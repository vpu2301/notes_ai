"""Download the speaker gold-set audio into ``eval/speakers/v1/audio/``.

    uv run python scripts/eval/fetch_speaker_corpus.py [--only ami-] [--pin]

Public files (AMI, VoxConverse) come from their official hosts over
HTTPS; ``<archive-url>#<member>`` (VoxConverse) downloads the archive
once into ``audio/_archives/`` and extracts the member. In-house files (``s3://notes-eval/...``) need the eval role:
``aws s3 cp`` with the caller's credentials — never a vendor, never git.
Every file is checked against ``audio_sha256``; ``--pin`` records the
hash and duration of files that have none yet (first fetch only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "eval" / "speakers" / "v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return round(float(out.stdout.strip()), 2)


def download(uri: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    if "#" in uri:
        archive_uri, member = uri.split("#", 1)
        archive = dest.parent / "_archives" / Path(archive_uri).name
        if not archive.exists():
            archive.parent.mkdir(exist_ok=True)
            download(archive_uri, archive)
        with zipfile.ZipFile(archive) as zf, zf.open(member) as src, tmp.open("wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)
    elif uri.startswith("s3://"):
        subprocess.run(["aws", "s3", "cp", "--only-show-errors", uri, str(tmp)], check=True)
    elif uri.startswith("https://"):
        with urllib.request.urlopen(uri, timeout=60) as resp, tmp.open("wb") as fh:  # noqa: S310
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
    else:
        raise SystemExit(f"unsupported audio_uri {uri!r}")
    tmp.rename(dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="id prefix filter")
    parser.add_argument("--pin", action="store_true", help="record sha256/duration where missing")
    args = parser.parse_args()

    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    audio_dir = ROOT / "audio"
    audio_dir.mkdir(exist_ok=True)
    failures = 0
    for entry in manifest["files"]:
        if not entry["id"].startswith(args.only):
            continue
        dest = audio_dir / f"{entry['id']}{Path(entry['audio_uri']).suffix or '.flac'}"
        if not dest.exists():
            print(f"fetch {entry['id']}", file=sys.stderr)
            download(entry["audio_uri"], dest)
        digest = sha256(dest)
        if entry.get("audio_sha256") is None and args.pin:
            entry["audio_sha256"] = digest
            entry["duration_s"] = duration_s(dest)
        elif entry.get("audio_sha256") != digest:
            print(f"SHA MISMATCH {entry['id']}: {digest}", file=sys.stderr)
            failures += 1
    if args.pin:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
