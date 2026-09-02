"""Permission-matrix exhaustive test.

The CSV at ``docs/auth/permissions.csv`` is the human-reviewable source of
truth. ``libs/auth.perms.ALLOW`` is the runtime gate. This file fails CI
if the two diverge — adding a permission means editing both.

Strategy:

1. Parse the CSV.
2. For every row, assert ``can(role, action, target) == row.allowed``.
3. Reject duplicate keys in the CSV.
4. Reject any (role, action, target) referenced by ``ALLOW`` that the CSV
   doesn't list — the CSV must be the *complete* allowlist documentation.
"""

import csv
from pathlib import Path

import pytest

from auth.claims import Claims
from auth.perms import (
    ALLOW,
    KNOWN_ROLES,
    KNOWN_TARGET_KINDS,
    AuthzDeniedError,
    can,
    check,
)

CSV_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "docs"
    / "auth"
    / "permissions.csv"
)


def _csv_rows() -> list[dict[str, str]]:
    assert CSV_PATH.exists(), f"missing CSV at {CSV_PATH}"
    with CSV_PATH.open() as f:
        return list(csv.DictReader(f))


def _make_claims(roles: list[str], scope: str = "") -> Claims:
    """A minimally-valid Claims object — only the fields perms checks reads."""
    from uuid import UUID

    return Claims(
        sub=UUID("11111111-1111-1111-1111-111111111111"),
        tid=UUID("00000000-0000-0000-0000-00000000000a"),
        roles=roles,
        scope=scope,
        mfa=False,
        sid="s",
        iss="i",
        aud="a",
        iat=0,
        exp=9999999999,
    )


# ── CSV ↔ code sync ─────────────────────────────────────────────────────


def test_csv_is_non_empty():
    rows = _csv_rows()
    assert len(rows) > 0


def test_csv_columns():
    rows = _csv_rows()
    assert set(rows[0].keys()) >= {"role", "action", "target_kind", "allowed"}


def test_csv_has_no_duplicate_keys():
    rows = _csv_rows()
    keys = [(r["role"], r["action"], r["target_kind"]) for r in rows]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, f"duplicate rows in CSV: {duplicates}"


def test_csv_uses_only_known_roles_and_targets():
    rows = _csv_rows()
    for r in rows:
        assert r["role"] in KNOWN_ROLES, f"unknown role {r['role']!r} in CSV"
        assert r["target_kind"] in KNOWN_TARGET_KINDS, f"unknown target {r['target_kind']!r} in CSV"


def test_every_csv_row_matches_can():
    """For every (role, action, target) in the CSV, can() returns CSV's allowed."""
    rows = _csv_rows()
    failures = []
    for r in rows:
        expected = r["allowed"].strip().lower() == "true"
        got = can(r["role"], r["action"], r["target_kind"])
        if got != expected:
            failures.append(
                f"{r['role']}/{r['action']}/{r['target_kind']}: CSV={expected} can()={got}"
            )
    assert not failures, "CSV ↔ code drift:\n" + "\n".join(failures)


def test_every_allow_entry_is_in_csv():
    """The CSV must be the *complete* documentation. Any (role, action,
    target) granted in code must appear (with allowed=true) in the CSV."""
    rows = _csv_rows()
    csv_allows = {
        (r["role"], r["action"], r["target_kind"])
        for r in rows
        if r["allowed"].strip().lower() == "true"
    }
    code_allows = {key for key, v in ALLOW.items() if v}
    missing = code_allows - csv_allows
    assert not missing, f"code grants not in CSV: {missing}"
    extra = csv_allows - code_allows
    assert not extra, f"CSV grants not in code: {extra}"


def test_matrix_is_complete_every_role_has_explicit_row():
    """Exhaustiveness: for every (action, target_kind) the CSV mentions,
    there is an explicit row for *every* known role — true or false.

    This makes deny a decision, never an accident. A new action that omits
    even one role fails CI here, forcing the author to make the call.
    """
    rows = _csv_rows()
    pairs = {(r["action"], r["target_kind"]) for r in rows}
    seen = {(r["role"], r["action"], r["target_kind"]) for r in rows}
    missing: list[str] = []
    for action, target in sorted(pairs):
        for role in sorted(KNOWN_ROLES):
            if (role, action, target) not in seen:
                missing.append(f"{role}/{action}/{target}")
    assert not missing, (
        "matrix incomplete — every (role × action × target_kind) needs an "
        "explicit true/false row:\n" + "\n".join(missing)
    )


# ── can() ────────────────────────────────────────────────────────────────


def test_can_default_is_deny():
    assert can("member", "audit.read", "audit") is False
    assert can("viewer", "user.invite", "user") is False


def test_negative_space_explicit_denies():
    """C4: things that MUST be denied across the CRUD surface. Each of these
    is an explicit ``false`` row in the CSV; this pins the intent in code."""
    # Only tenant_admin manages roles.
    assert can("viewer", "user.manage_roles", "user") is False
    assert can("member", "user.manage_roles", "user") is False
    assert can("auditor", "user.manage_roles", "user") is False
    assert can("service", "user.manage_roles", "user") is False
    # Auditor is read-only — no template writes.
    assert can("auditor", "template.update", "template") is False
    assert can("auditor", "template.clone", "template") is False
    assert can("auditor", "template.deprecate", "template") is False
    # Service tokens are not human dictation actors.
    assert can("service", "dictation.start", "dictation_session") is False
    assert can("service", "dictation.finalize", "dictation_session") is False
    # Reactivate is admin-only.
    assert can("member", "user.reactivate", "user") is False
    assert can("auditor", "user.reactivate", "user") is False
    # user.read is admin + auditor only.
    assert can("member", "user.read", "user") is False
    assert can("viewer", "user.read", "user") is False
    assert can("service", "user.read", "user") is False


def test_new_user_crud_grants():
    """The Part-A grants are present exactly where intended."""
    assert can("tenant_admin", "user.read", "user") is True
    assert can("auditor", "user.read", "user") is True
    assert can("tenant_admin", "user.manage_roles", "user") is True
    assert can("tenant_admin", "user.reactivate", "user") is True


def test_can_grants_match_csv():
    assert can("tenant_admin", "user.invite", "user") is True
    assert can("auditor", "audit.verify", "audit") is True
    assert can("member", "tenant.read", "tenant") is True


def test_can_unknown_role_or_action_is_deny():
    assert can("super_admin", "audit.read", "audit") is False
    assert can("tenant_admin", "note.summon_lawyer", "user") is False


# ── check(): role-based + scope-based ──────────────────────────────────


def test_check_passes_when_role_allows():
    claims = _make_claims(roles=["auditor"])
    # No exception.
    check(claims, action="audit.read", target_kind="audit")


def test_check_passes_with_any_matching_role():
    claims = _make_claims(roles=["member", "auditor"])
    check(claims, action="audit.read", target_kind="audit")  # ok via auditor


def test_check_raises_when_no_role_allows():
    claims = _make_claims(roles=["member"])
    with pytest.raises(AuthzDeniedError) as exc:
        check(claims, action="audit.read", target_kind="audit")
    assert exc.value.reason == "role_denied"
    assert exc.value.action == "audit.read"


def test_check_role_pass_but_scope_missing_raises():
    claims = _make_claims(roles=["auditor"], scope="openid email")
    with pytest.raises(AuthzDeniedError) as exc:
        check(claims, action="audit.read", target_kind="audit", scope="audit:read")
    assert exc.value.reason == "scope_missing"
    assert exc.value.required_scope == "audit:read"


def test_check_role_pass_and_scope_present_succeeds():
    claims = _make_claims(roles=["auditor"], scope="openid audit:read")
    check(claims, action="audit.read", target_kind="audit", scope="audit:read")


def test_check_empty_roles_is_deny():
    claims = _make_claims(roles=[])
    with pytest.raises(AuthzDeniedError):
        check(claims, action="tenant.read", target_kind="tenant")


# ── Admin ⟂ content separation ──────────────────────────────────────────
#
# A tenant_admin runs the workspace, not its content. These tests pin the
# boundary: an admin-only account holds no note/dictation/ASR content
# permission and reaches the dashboard only through `stats.read`.


def test_admin_holds_no_content_permissions():
    for action, target in (
        ("note.read", "note"),
        ("note.write", "note"),
        ("dictation.start", "dictation_session"),
        ("dictation.read", "dictation_session"),
        ("dictation.finalize", "dictation_session"),
        ("asr.read", "asr_job"),
        ("asr.write", "asr_job"),
        ("asr.cancel", "asr_job"),
    ):
        assert can("tenant_admin", action, target) is False, f"{action}/{target}"


def test_admin_keeps_the_aggregate_door():
    assert can("tenant_admin", "stats.read", "tenant") is True
    for role in ("member", "viewer", "auditor", "service"):
        assert can(role, "stats.read", "tenant") is False, role


def test_authors_hold_note_permissions():
    for role in ("member", "viewer"):
        assert can(role, "note.read", "note") is True, role
        assert can(role, "note.write", "note") is True, role
    assert can("auditor", "note.read", "note") is False
    assert can("service", "note.read", "note") is True  # S2S export pipeline
    assert can("service", "note.write", "note") is False


def test_device_holds_exactly_the_capture_grants():
    """Ambient capture: the `device` role (room hardware on client
    credentials) is capture-only. Pin the EXACT grant set — a compromised
    room device must not be able to read any tenant content."""
    expected = {
        ("tenant.read", "tenant"),
        ("asr.write", "asr_job"),
        ("asr.read", "asr_job"),
        ("dictation.start", "dictation_session"),
        ("dictation.read", "dictation_session"),
        ("dictation.finalize", "dictation_session"),
        ("template.read", "template"),
    }
    actual = {
        (action, target)
        for (role, action, target), allowed in ALLOW.items()
        if role == "device" and allowed
    }
    assert actual == expected


def test_device_denied_all_content_and_admin_reads():
    """Negative space that matters for the threat model: the device can
    ADD audio/transcripts but read no notes, users, audit, or stats."""
    for action, target in (
        ("note.read", "note"),
        ("note.write", "note"),
        ("user.read", "user"),
        ("audit.read", "audit"),
        ("stats.read", "tenant"),
        ("asr.cancel", "asr_job"),
        ("notification.read", "notification"),
        ("nlp.process", "nlp_text"),
        ("autocomplete.read", "phrase"),
        ("synonym.read", "synonym"),
        ("template.update", "template"),
    ):
        assert can("device", action, target) is False, f"{action}/{target}"


def test_device_claims_pass_capture_checks():
    claims = _make_claims(roles=["device"])
    check(claims, action="dictation.start", target_kind="dictation_session")
    check(claims, action="asr.write", target_kind="asr_job")
    with pytest.raises(AuthzDeniedError):
        check(claims, action="note.read", target_kind="note")


def test_dual_role_admin_member_keeps_authoring():
    """The matrix is over ROLES, not people. A member who also administers
    the tenant holds both roles, and `check()` passes on any granting
    role — the separation must not strip their authoring access."""
    both = _make_claims(roles=["tenant_admin", "member"])
    check(both, action="note.write", target_kind="note")  # no raise
    check(both, action="tenant.update", target_kind="tenant")  # no raise
