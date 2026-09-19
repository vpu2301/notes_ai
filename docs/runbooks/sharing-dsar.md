# Runbook — Data-subject requests for recipients

A recipient of a shared note has no account. Everything about them is
keyed by the address the sender typed, and it lives in exactly these
places:

| Where | What | Cleared by |
|---|---|---|
| `note_share_links.recipient_email` (sender's tenant) | the address, as a label and delivery target | revoke (`DELETE /v1/notes/{id}/links/{link_id}`), retention job, `erase_recipient.py` |
| `share_link_responses` on those links | confirm / done / dispute / flag + comment | author "Clear", retention job, `erase_recipient.py` |
| `share_link_otps` on those links | a code hash for ten minutes | verify, retention job, `erase_recipient.py` |
| `referrals.lead_email` | the `/join` fake-door address | `erase_lead.py`, `erase_recipient.py` |
| `share_mail_suppressions` | `sha256(pepper ‖ address)` after an unsubscribe | `erase_recipient.py` (unless `--keep-suppression`) |

Audit payloads never carry the address, a token, a code or a comment.

## Erase

    DB_TENANT_WRITER_DSN=... MDX_SHARE_MAIL_SUPPRESSION_PEPPER_HEX=... \
      uv run python scripts/ops/erase_recipient.py --email tom@client.com

Prints counts per kind. The links themselves keep working until they
expire — the recipient still holds them; ask the sender to revoke if the
request includes that.

## Access

The same script's queries, read-only, answer "what do you hold about me":
links (by label and dates, never the note content), responses (kind,
date, comment), whether an opt-out is recorded. Note content is the
sender's and is not part of the recipient's data.
