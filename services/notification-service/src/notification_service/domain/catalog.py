"""The category catalogue: who hears about what, and how, by default.

`test_catalog.py` asserts a 1:1 mapping onto `Category`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from notification_events import Category, EmailMode, Severity


class RecipientRule(StrEnum):
    """How to resolve a fact's audience; role-derived audiences are resolved here, not by the producer."""

    # Author + co-authors, minus the actor.
    NOTE_PARTICIPANTS = "note_participants"
    # Everyone with tenant_admin on the tenant.
    TENANT_ADMINS = "tenant_admins"
    # Exactly the users the producer named, verbatim.
    EXPLICIT_HINTS = "explicit_hints"


@dataclass(frozen=True, slots=True)
class CategorySpec:
    category: Category
    recipient_rule: RecipientRule

    # Defaults, overridable per user (domain/preferences.py).
    default_in_app: bool
    default_email_mode: EmailMode

    severity: Severity

    # May a user route this to the daily digest? Time-critical/failure categories say no.
    digest_eligible: bool

    # Whether the actor is excluded from their own fan-out.
    exclude_actor: bool = True

    # Template stem under `templates/email/`; empty = never emails (PII gate asserts this).
    email_template: str = ""


_SPECS: Final[tuple[CategorySpec, ...]] = (
    CategorySpec(
        category=Category.NOTE_FINALIZED,
        recipient_rule=RecipientRule.NOTE_PARTICIPANTS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.INFO,
        digest_eligible=True,
        # A solo author must be told about their own note.
        exclude_actor=False,
    ),
    CategorySpec(
        category=Category.NOTE_AMENDED,
        recipient_rule=RecipientRule.NOTE_PARTICIPANTS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.INFO,
        digest_eligible=True,
    ),
    CategorySpec(
        category=Category.NOTE_CHAIN_FAILURE,
        recipient_rule=RecipientRule.TENANT_ADMINS,
        default_in_app=True,
        default_email_mode=EmailMode.IMMEDIATE,
        severity=Severity.CRITICAL,
        digest_eligible=False,
        # System-raised: there is no actor to exclude.
        exclude_actor=False,
        email_template="note_chain_failure",
    ),
    CategorySpec(
        category=Category.NOTE_SHARED_WITH_YOU,
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        default_email_mode=EmailMode.IMMEDIATE,
        severity=Severity.INFO,
        digest_eligible=True,
        email_template="note_shared",
    ),
    CategorySpec(
        category=Category.NOTE_RECIPIENT_RESPONDED,
        # Author team by hint; the recipient has no account.
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        default_email_mode=EmailMode.DIGEST,
        severity=Severity.INFO,
        digest_eligible=True,
        email_template="note_recipient_responded",
    ),
    CategorySpec(
        category=Category.SHARE_REPORTED,
        recipient_rule=RecipientRule.TENANT_ADMINS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.WARNING,
        digest_eligible=False,
    ),
    CategorySpec(
        category=Category.AI_BUDGET_REACHED,
        recipient_rule=RecipientRule.TENANT_ADMINS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.WARNING,
        digest_eligible=False,
        # The "actor" is whoever crossed the line; they need telling too.
        exclude_actor=False,
    ),
    CategorySpec(
        category=Category.NOTE_LINK_STATUS_CHANGED,
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.INFO,
        digest_eligible=False,
    ),
    CategorySpec(
        category=Category.DICTATION_COMPLETED,
        # The dictating user, named by dictation-service.
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.INFO,
        digest_eligible=True,
        # The actor is the audience.
        exclude_actor=False,
    ),
    CategorySpec(
        category=Category.TRANSCRIPTION_COMPLETED,
        # The submitter, named by asr-worker.
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        default_email_mode=EmailMode.OFF,
        severity=Severity.INFO,
        digest_eligible=True,
        # The actor is the audience.
        exclude_actor=False,
    ),
    CategorySpec(
        category=Category.TRANSCRIPTION_FAILED,
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        # WARNING: severity drives how long the SPA toast lingers.
        severity=Severity.WARNING,
        digest_eligible=False,
        # Only actionable in the app, so no email and no template.
        default_email_mode=EmailMode.OFF,
        exclude_actor=False,
    ),
    CategorySpec(
        category=Category.SECURITY_MFA_REMINDER,
        # Exactly the user asked, never a broadcast: a missing second factor is a weakness.
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        default_in_app=True,
        severity=Severity.WARNING,
        # Emails because the un-enrolled user is often one the in-app banner never reaches.
        default_email_mode=EmailMode.IMMEDIATE,
        digest_eligible=False,
        # Actor (reviewer) and audience (subject) can never coincide.
        exclude_actor=False,
        email_template="security_mfa_reminder",
    ),
    CategorySpec(
        category=Category.SYSTEM_DIGEST,
        recipient_rule=RecipientRule.EXPLICIT_HINTS,
        # The digest is an email; an in-app copy is noise.
        default_in_app=False,
        default_email_mode=EmailMode.IMMEDIATE,
        severity=Severity.INFO,
        digest_eligible=False,
        exclude_actor=False,
        email_template="digest",
    ),
)

CATALOG: Final[dict[Category, CategorySpec]] = {spec.category: spec for spec in _SPECS}


def spec_for(category: Category) -> CategorySpec:
    """Look up a category; raises rather than guessing (unknown = contract mismatch, goes to DLQ)."""
    try:
        return CATALOG[category]
    except KeyError as exc:  # pragma: no cover — guarded by test_catalog
        raise KeyError(f"category {category!r} has no catalog entry") from exc


def digest_eligible_categories() -> frozenset[Category]:
    return frozenset(s.category for s in _SPECS if s.digest_eligible)


def emailing_categories() -> frozenset[Category]:
    """Categories that can ever produce an email (PII gate input)."""
    return frozenset(s.category for s in _SPECS if s.email_template)
