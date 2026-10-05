#!/usr/bin/env python3
"""Print the newest sign-in code Mailpit holds for one address (the mailbox is the only
place a code is observable). Stdlib only; run straight from Playwright.

    scripts/ci/mailpit-last-code.py someone@example.test [--wait 20] [--purge]

Exit 0 code printed, 1 no code inside the wait, 2 Mailpit unreachable.
Never point this at a real mail host.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://localhost:8025"

# Grouped ("482 913", `domain/compose.format_code`) or plain; anchored on
# non-digits so a longer number cannot be mistaken for a code.
CODE_RE = re.compile(r"(?<!\d)(\d{3})[  -]?(\d{3})(?!\d)")

# Sign-in-code subjects in every language `copy.py` renders; matching the
# subject keeps a security notice quoting a number from reading as a code.
SUBJECTS = (
    "sign-in code",  # en — "Your Notes AI sign-in code"
    "anmeldecode",  # de — "Ihr Notes AI-Anmeldecode"
    "код входу",  # uk — "Ваш код входу в Notes AI"
)


class MailpitUnreachableError(RuntimeError):
    """Mailpit did not answer. A broken fixture, not a failed assertion."""


def _get(base: str, path: str, **params: str) -> dict:
    url = f"{base.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — fixed dev host
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MailpitUnreachableError(f"{url}: {exc}") from exc


def _delete_all(base: str) -> None:
    req = urllib.request.Request(f"{base.rstrip('/')}/api/v1/messages", method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 — fixed dev host
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MailpitUnreachableError(f"purge: {exc}") from exc


def _is_code_mail(subject: str) -> bool:
    lowered = subject.casefold()
    return any(marker.casefold() in lowered for marker in SUBJECTS)


def _messages_for(base: str, email: str) -> list[dict]:
    """Newest first. Mailpit's search is `to:` scoped so one test's mail
    cannot be read by another running beside it."""
    query = _get(base, "/api/v1/search", query=f"to:{email}", limit="20")
    messages = query.get("messages") or []
    # Sort on `Created` rather than rely on Mailpit's order.
    return sorted(messages, key=lambda m: str(m.get("Created", "")), reverse=True)


def _code_in(base: str, message_id: str) -> str | None:
    body = _get(base, f"/api/v1/message/{message_id}")
    text = f"{body.get('Text') or ''}\n{body.get('HTML') or ''}"
    match = CODE_RE.search(text)
    return f"{match.group(1)}{match.group(2)}" if match else None


def last_code(base: str, email: str, *, wait_seconds: float) -> str | None:
    """Poll until a sign-in code for `email` arrives: SMTP delivery races the HTTP response."""
    deadline = time.monotonic() + wait_seconds
    while True:
        for message in _messages_for(base, email):
            if not _is_code_mail(str(message.get("Subject", ""))):
                continue
            code = _code_in(base, str(message["ID"]))
            if code:
                return code
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("email", help="the address the code was sent to")
    parser.add_argument(
        "--base", default=DEFAULT_BASE, help=f"Mailpit HTTP API (default {DEFAULT_BASE})"
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="how long to wait for the mail to arrive (default 15)",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete every message first, then wait for a fresh one",
    )
    args = parser.parse_args()

    try:
        if args.purge:
            _delete_all(args.base)
        code = last_code(args.base, args.email, wait_seconds=args.wait)
    except MailpitUnreachableError as exc:
        print(f"mailpit unreachable: {exc}", file=sys.stderr)
        print(
            "Is the dev stack up, and is auth-service pointed at it (MDX_AUTH_SMTP_HOST=mailpit)?",
            file=sys.stderr,
        )
        return 2

    if code is None:
        print(f"no sign-in code for {args.email} within {args.wait:g}s", file=sys.stderr)
        return 1
    print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
