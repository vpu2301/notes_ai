"""Permission matrix: ``(role, action, target_kind) → allowed``.

``ALLOW`` is the runtime gate; ``docs/auth/permissions.csv`` mirrors it and test_perms fails if they diverge.
"""

from __future__ import annotations

from typing import Final

from .claims import Claims

# Plain str (not Literal) so the CSV reads straight in; the exhaustive test guards typos.

Role = str  # tenant_admin | member | viewer | auditor | service | device
Action = str  # e.g. 'user.invite', 'audit.read'
TargetKind = str  # e.g. 'user', 'audit', 'tenant'

KNOWN_ROLES: Final[frozenset[str]] = frozenset(
    {"tenant_admin", "member", "viewer", "auditor", "service", "device"}
)

KNOWN_TARGET_KINDS: Final[frozenset[str]] = frozenset(
    {
        "tenant",
        "user",
        "audit",
        "asr_job",
        "dictation_session",
        "nlp_text",
        "abbreviation",
        "template",
        "note",
        "notification",
        "phrase",
        "synonym",
        # Credentials for non-human principals (room devices, service accounts).
        "credential",
    }
)


# Only "True" entries are listed; ``can`` defaults to deny. Mirror at docs/auth/permissions.csv.

ALLOW: Final[dict[tuple[Role, Action, TargetKind], bool]] = {
    # tenant_admin: tenant-wide admin
    ("tenant_admin", "tenant.read", "tenant"): True,
    # ai_settings: every member may read, only an admin may change.
    ("tenant_admin", "ai_settings.read", "tenant"): True,
    ("tenant_admin", "ai_settings.write", "tenant"): True,
    # Billing is admin-only, read included.
    ("tenant_admin", "billing.read", "tenant"): True,
    ("tenant_admin", "billing.write", "tenant"): True,
    ("tenant_admin", "tenant.update", "tenant"): True,
    ("tenant_admin", "tenant.create", "tenant"): True,
    ("tenant_admin", "tenant.manage_members", "tenant"): True,
    ("tenant_admin", "user.read", "user"): True,
    ("tenant_admin", "user.invite", "user"): True,
    ("tenant_admin", "user.manage_roles", "user"): True,
    ("tenant_admin", "user.deactivate", "user"): True,
    ("tenant_admin", "user.reactivate", "user"): True,
    ("tenant_admin", "user.reset_mfa", "user"): True,
    # remind_mfa asks for enrolment and touches nothing about the account (unlike reset_mfa).
    ("tenant_admin", "user.remind_mfa", "user"): True,
    ("tenant_admin", "audit.read", "audit"): True,
    ("tenant_admin", "audit.verify", "audit"): True,
    # Matrix is keyed on token roles, not memberships; a `tenant_admin` token proves
    # administration of ITS tenant only, so the route also checks workspace membership.
    ("tenant_admin", "device.manage", "credential"): True,
    ("member", "tenant.read", "tenant"): True,
    ("member", "ai_settings.read", "tenant"): True,
    ("viewer", "tenant.read", "tenant"): True,
    ("viewer", "ai_settings.read", "tenant"): True,
    ("auditor", "tenant.read", "tenant"): True,
    ("auditor", "ai_settings.read", "tenant"): True,
    ("auditor", "user.read", "user"): True,
    # The auditor's only write, deliberate: it changes nothing about the account.
    ("auditor", "user.remind_mfa", "user"): True,
    ("auditor", "audit.read", "audit"): True,
    ("auditor", "audit.verify", "audit"): True,
    # ── Batch transcription (ASR); tenant_admin deliberately absent (admin ⟂ content) ──
    ("member", "asr.write", "asr_job"): True,
    ("member", "asr.read", "asr_job"): True,
    ("member", "asr.cancel", "asr_job"): True,
    ("viewer", "asr.write", "asr_job"): True,
    ("viewer", "asr.read", "asr_job"): True,
    ("service", "asr.read", "asr_job"): True,
    ("service", "asr.write", "asr_job"): True,
    # ── Streaming dictation; tenant_admin deliberately absent ──────────
    ("member", "dictation.start", "dictation_session"): True,
    ("member", "dictation.read", "dictation_session"): True,
    ("member", "dictation.finalize", "dictation_session"): True,
    ("viewer", "dictation.start", "dictation_session"): True,
    ("viewer", "dictation.read", "dictation_session"): True,
    ("viewer", "dictation.finalize", "dictation_session"): True,
    ("service", "dictation.read", "dictation_session"): True,
    # ── NLP post-processing ────────────────────────────────────────────
    ("tenant_admin", "nlp.process", "nlp_text"): True,
    ("member", "nlp.process", "nlp_text"): True,
    ("viewer", "nlp.process", "nlp_text"): True,
    ("service", "nlp.process", "nlp_text"): True,
    ("tenant_admin", "nlp.read.abbreviations", "abbreviation"): True,
    ("tenant_admin", "nlp.write.abbreviations", "abbreviation"): True,
    ("member", "nlp.read.abbreviations", "abbreviation"): True,
    ("viewer", "nlp.read.abbreviations", "abbreviation"): True,
    ("auditor", "nlp.read.abbreviations", "abbreviation"): True,
    ("service", "nlp.read.abbreviations", "abbreviation"): True,
    # ── Note templates ─────────────────────────────────────────────────
    ("tenant_admin", "template.read", "template"): True,
    ("tenant_admin", "template.clone", "template"): True,
    ("tenant_admin", "template.update", "template"): True,
    ("tenant_admin", "template.deprecate", "template"): True,
    ("member", "template.read", "template"): True,
    ("viewer", "template.read", "template"): True,
    ("auditor", "template.read", "template"): True,
    ("service", "template.read", "template"): True,
    # ── Notes; auditors denied content, service read-only, tenant_admin deliberately absent ──
    ("member", "note.write", "note"): True,
    ("member", "note.read", "note"): True,
    ("viewer", "note.write", "note"): True,
    ("viewer", "note.read", "note"): True,
    ("service", "note.read", "note"): True,
    # ── Notifications: every session-holding role, auditor included; rows are the caller's own ──
    ("tenant_admin", "notification.read", "notification"): True,
    ("tenant_admin", "notification.write", "notification"): True,
    ("member", "notification.read", "notification"): True,
    ("member", "notification.write", "notification"): True,
    ("viewer", "notification.read", "notification"): True,
    ("viewer", "notification.write", "notification"): True,
    ("auditor", "notification.read", "notification"): True,
    ("auditor", "notification.write", "notification"): True,
    # ── Admin ⟂ content: tenant_admin has no `asr.*`/`dictation.*`/`note.*`. Roles, not people:
    # an admin who is also a member keeps authoring access via `member`.
    # stats.read gates PII-free aggregate reads (counts and timings only).
    ("tenant_admin", "stats.read", "tenant"): True,
    # ── Autocomplete phrases (decoupled from note.*) ───────────────────
    ("tenant_admin", "autocomplete.read", "phrase"): True,
    ("tenant_admin", "autocomplete.write", "phrase"): True,
    ("member", "autocomplete.read", "phrase"): True,
    ("member", "autocomplete.write", "phrase"): True,
    ("viewer", "autocomplete.read", "phrase"): True,
    ("viewer", "autocomplete.write", "phrase"): True,
    ("service", "autocomplete.read", "phrase"): True,
    # ── Synonyms (ADR-0038): search metadata, never note content ───────
    ("member", "synonym.read", "synonym"): True,
    ("viewer", "synonym.read", "synonym"): True,
    ("service", "synonym.read", "synonym"): True,
    ("tenant_admin", "synonym.read", "synonym"): True,
    ("tenant_admin", "synonym.write", "synonym"): True,
    # ── Ambient capture devices: capture only, no content surface (threat model: a stolen box).
    # template.read because a conversation session loads its template on start.
    ("device", "tenant.read", "tenant"): True,
    ("device", "asr.write", "asr_job"): True,
    ("device", "asr.read", "asr_job"): True,
    ("device", "dictation.start", "dictation_session"): True,
    ("device", "dictation.read", "dictation_session"): True,
    ("device", "dictation.finalize", "dictation_session"): True,
    ("device", "template.read", "template"): True,
}


class AuthzDeniedError(Exception):
    """Role check failed. Distinct from ``HTTPException`` so callers can audit before mapping to 403."""

    def __init__(
        self,
        *,
        action: Action,
        target_kind: TargetKind,
        claims: Claims,
        reason: str = "role_denied",
        required_scope: str | None = None,
    ) -> None:
        super().__init__(
            f"deny: roles={list(claims.roles)} cannot {action!r} on {target_kind!r} "
            f"(reason={reason})"
        )
        self.action = action
        self.target_kind = target_kind
        self.claims = claims
        self.reason = reason
        self.required_scope = required_scope


def can(role: Role, action: Action, target_kind: TargetKind) -> bool:
    """Return ``True`` iff the matrix has an explicit allow for the tuple."""
    return ALLOW.get((role, action, target_kind), False)


def can_claims(claims: Claims, action: Action, target_kind: TargetKind) -> bool:
    """``True`` iff any of the caller's roles grants the tuple (the predicate form of :func:`check`)."""
    return any(can(role, action, target_kind) for role in claims.roles)


def check_any(
    claims: Claims,
    *,
    options: tuple[tuple[Action, TargetKind], ...],
) -> None:
    """Pass if ANY pair is granted; a denial is reported against the FIRST (primary) option."""
    if not options:
        raise ValueError("check_any requires at least one option")
    for action, target_kind in options:
        if can_claims(claims, action, target_kind):
            return
    action, target_kind = options[0]
    raise AuthzDeniedError(
        action=action,
        target_kind=target_kind,
        claims=claims,
        reason="role_denied",
    )


def check(
    claims: Claims,
    *,
    action: Action,
    target_kind: TargetKind,
    scope: str | None = None,
) -> None:
    """Raise :class:`AuthzDeniedError` unless a role allows the action and ``scope`` (if given) is held."""
    if not any(can(role, action, target_kind) for role in claims.roles):
        raise AuthzDeniedError(
            action=action,
            target_kind=target_kind,
            claims=claims,
            reason="role_denied",
        )
    if scope is not None:
        token_scopes = claims.scope.split() if claims.scope else []
        if scope not in token_scopes:
            raise AuthzDeniedError(
                action=action,
                target_kind=target_kind,
                claims=claims,
                reason="scope_missing",
                required_scope=scope,
            )
