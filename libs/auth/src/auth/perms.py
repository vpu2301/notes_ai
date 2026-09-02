"""Permission matrix: ``(role, action, target_kind) → allowed``.

The ``ALLOW`` dict is the runtime gate. The CSV at
``docs/auth/permissions.csv`` is the human-reviewable source of truth.
The exhaustive test ``libs/auth/tests/unit/test_perms.py`` fails CI if
the two ever diverge — adding a new permission means editing both, and
the test verifies they match.
"""

from __future__ import annotations

from typing import Final

from .claims import Claims

# ── Domain literals ─────────────────────────────────────────────────────
# Kept as plain str so we can read them from the CSV without a Literal
# bridge. The exhaustive test guards against typos.

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
    }
)


# ── The matrix ──────────────────────────────────────────────────────────
# Only "True" entries are listed; ``can`` defaults to deny.
# Mirror at docs/auth/permissions.csv.

ALLOW: Final[dict[tuple[Role, Action, TargetKind], bool]] = {
    # tenant_admin: tenant-wide admin
    ("tenant_admin", "tenant.read", "tenant"): True,
    ("tenant_admin", "tenant.update", "tenant"): True,
    ("tenant_admin", "tenant.create", "tenant"): True,
    ("tenant_admin", "tenant.manage_members", "tenant"): True,
    ("tenant_admin", "user.read", "user"): True,
    ("tenant_admin", "user.invite", "user"): True,
    ("tenant_admin", "user.manage_roles", "user"): True,
    ("tenant_admin", "user.deactivate", "user"): True,
    ("tenant_admin", "user.reactivate", "user"): True,
    ("tenant_admin", "user.reset_mfa", "user"): True,
    # Ask a user to enrol a second factor. Distinct from reset_mfa, which
    # CLEARS one — this touches nothing about the account, which is why
    # the auditor holds it too (see the auditor block below).
    ("tenant_admin", "user.remind_mfa", "user"): True,
    ("tenant_admin", "audit.read", "audit"): True,
    ("tenant_admin", "audit.verify", "audit"): True,
    # member: routine authoring user (creates and edits notes)
    ("member", "tenant.read", "tenant"): True,
    # viewer: like member but with less admin capability
    ("viewer", "tenant.read", "tenant"): True,
    # auditor: read-only audit access + tenant context. user.read gives the
    # auditor read-only visibility of the tenant's user roster.
    ("auditor", "tenant.read", "tenant"): True,
    ("auditor", "user.read", "user"): True,
    # The auditor's ONLY write in the whole matrix, and it is deliberate:
    # an access review that can see an account without a second factor but
    # cannot ask for one produces a finding nobody acts on. The act changes
    # nothing about the account — no role, no status, no credential — it
    # records a request that only the SUBJECT can close, by enrolling. That
    # asymmetry is what keeps the read-only role read-only.
    ("auditor", "user.remind_mfa", "user"): True,
    ("auditor", "audit.read", "audit"): True,
    ("auditor", "audit.verify", "audit"): True,
    # ── Batch transcription (ASR) ──────────────────────────────────────
    # tenant_admin is DELIBERATELY absent from asr.* — see the
    # admin/content separation block at the bottom of this matrix.
    ("member", "asr.write", "asr_job"): True,
    ("member", "asr.read", "asr_job"): True,
    ("member", "asr.cancel", "asr_job"): True,
    # Viewers can submit and read their own; cancel still goes through
    # member/admin.
    ("viewer", "asr.write", "asr_job"): True,
    ("viewer", "asr.read", "asr_job"): True,
    # Service tokens (asr-worker → audit/storage) need read+write:
    ("service", "asr.read", "asr_job"): True,
    ("service", "asr.write", "asr_job"): True,
    # ── Streaming dictation ────────────────────────────────────────────
    # tenant_admin is DELIBERATELY absent — see the admin/content block.
    ("member", "dictation.start", "dictation_session"): True,
    ("member", "dictation.read", "dictation_session"): True,
    ("member", "dictation.finalize", "dictation_session"): True,
    ("viewer", "dictation.start", "dictation_session"): True,
    ("viewer", "dictation.read", "dictation_session"): True,
    ("viewer", "dictation.finalize", "dictation_session"): True,
    # Service tokens (S2S between dictation-service and NLP):
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
    # Service tokens read templates to load them for dictation/nlp:
    ("service", "template.read", "template"): True,
    # ── Notes (versioning, diff, search) ───────────────────────────────
    # Authors (member, viewer) read+write; auditors denied content;
    # service tokens read-only (PDF/export pipeline S2S reads).
    # tenant_admin is DELIBERATELY absent — see the admin/content block.
    ("member", "note.write", "note"): True,
    ("member", "note.read", "note"): True,
    ("viewer", "note.write", "note"): True,
    ("viewer", "note.read", "note"): True,
    ("service", "note.read", "note"): True,
    # ── Notifications ──────────────────────────────────────────────────
    # Every role that can hold a session gets both, INCLUDING auditor:
    # these act only on the caller's OWN notification rows (the endpoints
    # take no user_id and the queries filter on recipient_user_id), so
    # this grants no visibility into note content. Withholding it would
    # leave an auditor unable to read or dismiss alerts addressed to them.
    ("tenant_admin", "notification.read", "notification"): True,
    ("tenant_admin", "notification.write", "notification"): True,
    ("member", "notification.read", "notification"): True,
    ("member", "notification.write", "notification"): True,
    ("viewer", "notification.read", "notification"): True,
    ("viewer", "notification.write", "notification"): True,
    ("auditor", "notification.read", "notification"): True,
    ("auditor", "notification.write", "notification"): True,
    # ── Admin ⟂ content separation ─────────────────────────────────────
    # A tenant_admin runs the workspace, not its content. The blocks above
    # deliberately drop tenant_admin from `asr.*`, `dictation.*` and
    # `note.*`: an administrator has no standing need to read members'
    # dictations or notes.
    #
    # Note this is a matrix over ROLES, not people: a member who also
    # administers the tenant holds BOTH `tenant_admin` and `member`, and
    # `check()` passes on any granting role — so their authoring access is
    # unchanged. It is the admin-ONLY account that loses the content
    # surfaces.
    #
    #   stats.read — PII-free aggregate reads. Gates the list endpoints
    #                the business dashboard aggregates (note search,
    #                dictation sessions, ASR jobs) in a stripped mode:
    #                no title, no snippet, no transcript, no result URL.
    #                Counts and timings only.
    ("tenant_admin", "stats.read", "tenant"): True,
    # ── Autocomplete phrases (decoupled from note.*) ───────────────────
    # Curating the tenant phrase library is administration, not authorship;
    # members/viewers write their own user-scope phrases.
    ("tenant_admin", "autocomplete.read", "phrase"): True,
    ("tenant_admin", "autocomplete.write", "phrase"): True,
    ("member", "autocomplete.read", "phrase"): True,
    ("member", "autocomplete.write", "phrase"): True,
    ("viewer", "autocomplete.read", "phrase"): True,
    ("viewer", "autocomplete.write", "phrase"): True,
    ("service", "autocomplete.read", "phrase"): True,
    # ── Synonyms (search query expansion, ADR-0038) ────────────────────
    # The dictionary is search metadata, not note content: reading it
    # rides along with searching; writing tenant entries is an admin
    # curation act — synonym rows carry dictionary terms, never note
    # content.
    ("member", "synonym.read", "synonym"): True,
    ("viewer", "synonym.read", "synonym"): True,
    ("service", "synonym.read", "synonym"): True,
    ("tenant_admin", "synonym.read", "synonym"): True,
    ("tenant_admin", "synonym.write", "synonym"): True,
    # ── Ambient capture devices ────────────────────────────────────────
    # `device` is room-capture hardware (a meeting-room microphone box)
    # authenticating via Keycloak client credentials. It CAPTURES only:
    # it can upload audio and stream/finalize dictation sessions, and
    # read back its own transcription jobs to confirm delivery — but it
    # holds no note, user, audit or notification surface. The threat
    # model is a stolen/compromised box on an office shelf: with this
    # grant set it cannot read any tenant content, only add new
    # audio/transcripts. template.read is needed because a conversation
    # session loads its template on start.
    ("device", "tenant.read", "tenant"): True,
    ("device", "asr.write", "asr_job"): True,
    ("device", "asr.read", "asr_job"): True,
    ("device", "dictation.start", "dictation_session"): True,
    ("device", "dictation.read", "dictation_session"): True,
    ("device", "dictation.finalize", "dictation_session"): True,
    ("device", "template.read", "template"): True,
}


class AuthzDeniedError(Exception):
    """Raised by ``requires()``-shaped deps when a role check fails.

    Distinct from ``HTTPException`` so callers can choose to emit an audit
    event before mapping to 403. The auth-service does exactly that — see
    ``services/auth-service/src/auth_service/deps.py``.
    """

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
    """``True`` iff any of the caller's roles grants the tuple.

    The predicate form of :func:`check` — for handlers that must *branch*
    on a permission rather than refuse without it (a note search that
    answers in stripped, PII-free form when the caller only holds
    ``stats.read``).
    """
    return any(can(role, action, target_kind) for role in claims.roles)


def check_any(
    claims: Claims,
    *,
    options: tuple[tuple[Action, TargetKind], ...],
) -> None:
    """Pass if ANY of the ``(action, target_kind)`` pairs is granted.

    For endpoints reachable by two different standings — a member's full
    content read, or an admin's PII-free aggregate read. The denial is
    reported against the FIRST option, which is by convention the
    primary/most-privileged one, so the audit row and the 403 name the
    permission the caller was most likely reaching for.
    """
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
    """Raise :class:`AuthzDeniedError` if none of the caller's roles allow
    the action, or if ``scope`` is required but missing from ``claims.scope``.

    Pure / framework-free — both libs/auth tests and the auth-service dep
    call this same function.
    """
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
