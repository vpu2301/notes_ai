#!/usr/bin/env python3
"""Read the newest sign-in code Mailpit holds for one address.

The end-to-end tests cannot see a code any other way. `/auth/email/start`
answers 202 for every syntactically valid address by construction — known,
unknown, locked and undeliverable are indistinguishable — so there is no
response field, no header and no log line to scrape. The only honest place
to look is the mailbox, and in dev and CI that mailbox is Mailpit.

    scripts/ci/mailpit-last-code.py someone@example.test
    scripts/ci/mailpit-last-code.py someone@example.test --wait 20
    scripts/ci/mailpit-last-code.py someone@example.test --purge

Prints the six digits and nothing else, so a caller can use it directly:

    CODE="$(scripts/ci/mailpit-last-code.py "$EMAIL" --wait 20)"

Exit 0 = a code was printed. Exit 1 = no matching mail inside the wait, or
mail that carried no code. Exit 2 = Mailpit itself is unreachable, which is
a broken fixture rather than a failed assertion and deserves a different
signal.

Stdlib only, and `python3` in the shebang rather than the `python` the rest
of `scripts/ci/` uses: those run under `uv run`, which supplies the name.
This one is executed straight from a Playwright process, where a stock
macOS box has only `python3` on PATH — and `uv run` for a URL fetch would
put a project resolve in the middle of a browser test.

**Never point this at a real mail host.** It is a fixture for a sink that
holds other people's one-time credentials in plaintext; `--purge` exists so
a test can guarantee the code it reads is the one its own step caused.
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

# The mail shows the code grouped ("482 913" — `domain/compose.format_code`),
# and a client may show it either way, so both forms are accepted. Anchored
# on non-digits so a longer number in the body cannot be mistaken for one.
CODE_RE = re.compile(r"(?<!\d)(\d{3})[  -]?(\d{3})(?!\d)")

# The subject line of the sign-in-code mail, in every language `copy.py`
# renders. Matching the subject rather than the body keeps a security
# notice that happens to quote a number from being read as a code.
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
    # Mailpit returns newest first already; sorting on `Created` makes that
    # a property of this script rather than of the version installed.
    return sorted(messages, key=lambda m: str(m.get("Created", "")), reverse=True)


def _code_in(base: str, message_id: str) -> str | None:
    body = _get(base, f"/api/v1/message/{message_id}")
    text = f"{body.get('Text') or ''}\n{body.get('HTML') or ''}"
    match = CODE_RE.search(text)
    return f"{match.group(1)}{match.group(2)}" if match else None


def last_code(base: str, email: str, *, wait_seconds: float) -> str | None:
    """Poll until a sign-in code for `email` arrives, or the wait runs out.

    Polling rather than a single read because SMTP delivery races the HTTP
    response that triggered it: `/auth/email/start` returns as soon as the
    provider accepted the message, which is before Mailpit has indexed it.
    """
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
