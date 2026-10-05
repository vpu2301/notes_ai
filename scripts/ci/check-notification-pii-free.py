#!/usr/bin/env python
"""BLOCKING CI gate: no email template may render note content or personal data
(ADR-0031). Renders every category against a poisoned payload and fails if a
token survives, a template is missing, or a Jinja placeholder is left unfilled.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/notification-service/src"))
sys.path.insert(0, str(ROOT / "libs/notification_events/src"))

from datetime import UTC, datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from notification_events import Category, NotificationEvent  # noqa: E402
from notification_service.adapters.templates import render_email  # noqa: E402
from notification_service.domain.catalog import CATALOG, emailing_categories  # noqa: E402
from notification_service.domain.render import (  # noqa: E402
    ALLOWED_PAYLOAD_KEYS,
    deep_link,
    safe_payload,
)

# Tokens that must NEVER reach a rendered email (realistic: surname, tax id,
# note-content fragment, date of birth, phone number).
PII_TOKENS: tuple[str, ...] = (
    "Іваненко",
    "Ivanenko",
    "3216549870",  # tax id
    "acquisition closes March 3",
    "salary review",
    "1978-04-12",  # DOB
    "+380671234567",
)
# NOT tokens: bare nouns like "note" occur in legitimate boilerplate; a gate
# that fails every template gets muted.

# A careless producer's payload; every sensitive key must be dropped by the allow-list.
POISONED_PAYLOAD: dict[str, str | int | float | bool | None] = {
    # Legitimate, allow-listed keys — these SHOULD appear.
    "note_code": "NOTE-2026-0042",
    "check_name": "chain_reconciler",
    "shared_by_display": "A colleague",
    "version": "3",
    "count": "5",
    "period": "day",
    # Personal data / note content a producer must never surface.
    "author_name": "Ivanenko Petro",
    "author_name_uk": "Іваненко Петро",
    "tax_id": "3216549870",
    "summary": "acquisition closes March 3, offer 2.1M",
    "agenda": "salary review for the sales team",
    "dob": "1978-04-12",
    "phone": "+380671234567",
    "note_title": "Ivanenko deal — acquisition closes March 3",
}


def _event(category: Category) -> NotificationEvent:
    # Built through the real model so the gate exercises the real path.
    return NotificationEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        category=category,
        actor_user_id=uuid4(),
        resource_type="note",
        resource_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload=POISONED_PAYLOAD,
    )


def main() -> int:
    failures: list[str] = []
    checked = 0

    categories = sorted(emailing_categories(), key=str)
    if not categories:
        print("FAIL: no emailing categories found — the gate would be vacuous")
        return 1

    for category in categories:
        spec = CATALOG[category]
        event = _event(category)
        fields = safe_payload(event)
        link = deep_link(event, base_url="https://app.example")

        try:
            rendered = render_email(
                category,
                template_stem=spec.email_template,
                fields=fields,
                deep_link=link,
                items=["Note NOTE-2026-0042 finalized"],
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{category}: template {spec.email_template!r} failed: {exc}")
            continue

        checked += 1
        surfaces = {
            "subject": rendered.subject,
            "text": rendered.text_body,
            "html": rendered.html_body,
        }

        for surface_name, content in surfaces.items():
            for token in PII_TOKENS:
                if token.lower() in content.lower():
                    failures.append(
                        f"{category}: PII/content token {token!r} leaked into the "
                        f"{surface_name} of template {spec.email_template!r}"
                    )
            # The template referenced something the allow-list does not provide.
            if "{{" in content or "{%" in content:
                failures.append(f"{category}: unrendered Jinja placeholder in {surface_name}")

        # Actionability: a mail about a note must carry the code; one with no
        # resource pointer (security.mfa_reminder) must carry the link.
        body = rendered.subject + rendered.text_body
        if "note_code" in ALLOWED_PAYLOAD_KEYS.get(category, frozenset()):
            if "NOTE-2026-0042" not in body:
                failures.append(
                    f"{category}: note_code missing from the rendered mail — "
                    "the pointer is what makes the notification actionable"
                )
        elif link not in rendered.text_body + rendered.html_body:
            failures.append(
                f"{category}: neither a resource pointer nor the deep link "
                "survived into the mail — nothing about it is actionable"
            )

    if failures:
        print("FAIL: notification email PII gate")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(
        f"PASS: {checked} email template(s) rendered free of note content and "
        f"personal data against {len(PII_TOKENS)} poisoned tokens"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
