# Concept — Workspaces & collaboration ("one account, any number of workspaces, anyone in a note")

**Status:** Hypothesis with a strong-signal problem behind it · **Owner:** Product · **Date:** 2026-10-12
**Companion:** `00-README-for-claude-code.md` (what exists, rules), sprints `W1`–`W4`.

## 1. The problem, in the user's words

Today a person *is* a workspace. The account you sign up with becomes "Tom's workspace", your notes live there, and the only ways to let someone else in are (a) an admin adding an existing user to the same tenant through a settings page, or (b) a read-only link to one note. There is no way to create a second workspace and name it, no way to invite an address that has no account, no way to give a colleague edit rights on one note but not on everything, and no way for an outside party to collaborate without becoming a full member. The founder's framing: *"the user can create an organization or not; the user can create a workspace and name it; the user can invite other people inside or outside the platform to a note and to a workspace, like Figma."*

## 2. Evidence

| Evidence | Confidence | Implication |
|---|---|---|
| Review research (project doc *"Why Users Are Dissatisfied with AI Note-Taking Apps"*): "notes trapped in one user's account", weak sharing, no team context is a recurring collaboration-failure theme across tools | Strong signal | The wedge is not "more features", it is *the note is where the team already is* |
| Same research: bot-based tools "spread like viruses" and are resented; IT blocks them | Strong signal | Growth must come from **invited** access, value-first for the invitee (same rule as the viral-loop concept) |
| Sprint 19–23 (recipient links) shipped a no-account read path; the loop metric is referred workspaces per 100 views | Proven path exists | Collaboration must not cannibalise it: links stay the no-signup path, invitations are the signup path |
| Codebase: `tenant_memberships` is many-to-many, `identities` + `auth_sessions.tenant_id` + `POST /auth/token` exist, all three clients ship a switcher — all dead under `MDX_IDP_MODE=keycloak` | Proven (code) | The cheapest big win is *turning on* the model the IDX track built, then filling the two real gaps: invitations and per-note roles |
| Codebase: anyone who can view a note can edit it (`require_view` on `PUT /draft`); transcripts are readable by any member of the tenant (asr-service checks `asr.read` only) | Proven (code) | Sharing more widely without roles would turn a trust feature into a trust failure. Roles and transcript gating are prerequisites of sharing, not polish |
| Founder answers (2026-10-12): org = optional billing/admin shell; many workspaces + personal; outsiders get accounts as guests; shared access without live co-editing; workspace-visible by default; note + evidence by role, transcript/audio gated; tenants → workspaces 1:1; order foundation → workspaces → note sharing → org | Decision | Recorded in README "Decisions already made" |

What we do **not** have: a count of how often a user wanted to share and could not, or how many invited colleagues never signed up. W1 instruments both (`share.blocked_no_account`, invitation funnel) so W2/W3 reviews run on numbers.

## 3. Jobs to be done

1. *When I start working with a new client or team, I want a named place for those meetings, so their notes, glossary and sharing rules stay separate from my other work, without creating a second account.*
2. *When a meeting ends, I want the people who were in it — on my team or not — to see the note and its commitments where they already work, so follow-up happens without me forwarding PDFs.*
3. *When I give a colleague access to a note, I want to decide whether they can change it, so a shared note stays a trusted record.*
4. *When an outside party needs to collaborate on one note, I want to invite them to exactly that, so nothing else in my workspace is exposed.*
5. *When I run a company with several teams, I want one bill and one member list, so I am not administering five workspaces by hand.* (Hypothesis — nobody has asked yet; §10.)

## 4. Thesis

For **small teams and the independents who work with them** (consultants, agencies, founders — the recipient-loop ICP), who struggle with **meeting knowledge trapped in one person's account**, the workspace model makes the note **the shared, role-controlled record of the meeting** across the people who were in it. Unlike bot-style tools that spread by recording everyone, we spread by **invitation to something already useful**, and unlike link-only sharing we give the invitee a **durable identity, a role and a place** so the second meeting is easier than the first.

## 5. Target model

```
identity ─┬─ membership(role) ─► workspace (tenant) ─┬─ note ─┬─ note_collaborator(role)
          │                       kind personal|team  │        ├─ note_comment
          │                       organization_id? ───┘        └─ note_share_link (no account)
          └─ invitation(email, workspace, role, note?) ──► membership (+ collaborator)
organization ─ organization_membership(role) ─ many workspaces (W4, optional)
```

| Concept | Table | Rules |
|---|---|---|
| Identity | `identities` | One per e-mail. Signs in by e-mail code (native) or password (`credentials`). |
| Workspace | `tenants` | `kind=personal` (one per identity, auto, undeletable) or `team` (user-created, named, renamable, dissolvable by the owner). |
| Membership | `tenant_memberships` | `owner` (≥ 1, full control, billing), `admin` (members, settings, sees all workspace-visible notes), `member` (records, edits workspace-visible notes), `viewer` (reads/comments workspace-visible notes), `guest` (sees only notes it was given). `status active|invited|suspended`. |
| Invitation | `tenant_invitations` | E-mail + role (+ optional `note_id` + note role). Expires 14 days. Accepting requires signing in as that address. |
| Note access | `notes.visibility` + `note_collaborators` | `private`: author team + collaborators by role. `workspace`: members edit, viewers comment, guests nothing, plus collaborators. |
| Comment | `note_comments` | Anchored to a section or item, plain text ≤ 2 000 chars, editable by author, resolvable by anyone who can edit the note. |
| Organization | `organizations` (W4) | Optional. Owns billing, default policies, member directory. Workspaces attach/detach. |

**Token roles** stay what `libs/auth/perms.py` knows (`tenant_admin`, `member`, `viewer`, + `guest`), mapped from the membership role per workspace by `identity_repository.platform_roles_for`. The product-side rule that turns a role into "may edit *this* note" lives in `note_service/domain/access.py` and nowhere else.

**Automation safety (PO OS §23):** inviting is Level 3 (external communication) — always an explicit act with a preview of what the invitee will get; adding a member who already has an account to a workspace is Level 2 (reversible: remove); changing someone's role down or removing them is reversible; dissolving a workspace is Level 4 (type the name, owner only, 30-day undo through support runbook).

## 6. Experience principles for this track

- The first workspace is already there. Nobody configures anything before their first meeting.
- Switching is one click and the whole app follows — tabs, uploads in flight, notifications, deep links. A wrong-workspace write is a P0 bug, not an edge case.
- Sharing starts from the note, not from settings. "Share" is one dialog: people (by role), the workspace, the client link.
- An invitee's first screen is the thing they were invited to, not a dashboard.
- Guests and viewers see less; they never see a disabled button for something they are not allowed to do — the capability is absent.

## 7. Metrics

**Track metric (dependency, not vanity):** share of weekly-active workspaces with ≥ 2 active members who each opened ≥ 1 note in the week ("collaborative workspaces"). Target after W3: ≥ 25 % of team workspaces (Speculation — set the bar from W2's baseline).

| Area | Metric | Source |
|---|---|---|
| Activation | invitations sent / new team workspace in first 7 days; invite → accepted (by has-account / no-account); accepted → first note opened ≤ 24 h | auth-service audit + `invitation.*` counters |
| Engagement | notes opened by non-author / notes opened; comments per shared note; "Shared with me" opens | note-service counters |
| Trust | edits by `view`/`comment` collaborators (must be 0 — server refuses); transcript reads by people without transcript access (0); wrong-workspace creates (0) | isolation suite + audit |
| Reliability | switch success rate; p95 of `POST /auth/token`; sessions healed to personal after membership loss | auth-service metrics |
| Growth | guest → own team workspace within 30 days (feeds the viral-loop K-factor) | referrals/cohort SQL |
| Guardrails | recipient-link share rate does not fall after invitations exist; support tickets "I can't find my note" do not rise; `/v1/notes/search` p95 unchanged with the collaborator join | existing dashboards |

## 8. Risks

| Risk | Mitigation |
|---|---|
| The IdP cut-over (W1) is the riskiest step and the least visible | Dual mode first; a scripted smoke of every sign-in/refresh/switch path on all three clients; the flip to `native` is a gated W4 item |
| Sharing more widely exposes transcripts/audio that today are reachable by any member | W3 gates transcripts by the note *before* widening sharing; the isolation suite walks every id route as a `view` collaborator and a guest |
| Two parallel sharing paths (invitations, links) confuse users | One dialog, explicit copy: "Invite (they sign in)" vs "Send a link (no account)" |
| Organization shell is built for nobody | §10 gate; W4's org part is an experiment with kill criteria |
| Free-tier seat limit promised but unenforced | Meter shown; enforcement explicitly NOT NOW; pricing owns it |

## 9. Not now (mandatory)

- Real-time co-editing, cursors, CRDT/OT.
- SSO/SAML, SCIM, domain-capture ("everyone @acme.com joins automatically"), enterprise audit console.
- Public/discoverable workspaces, join requests, workspace directories.
- Nested folders shared per folder (spaces stay personal, `note_spaces.user_sub`).
- Per-section or per-item permissions inside a note.
- @-mentions, reactions, threaded replies, e-mail replies to comments.
- Transferring a note between workspaces (manual re-record/import only).
- Seat-limit enforcement, per-seat billing, org-level invoicing beyond "plan on the org".
- Migrating `calendar_connections` or MCP connectors to be workspace-independent (debt issue; W1 only documents the behaviour).
- Windows, Android.

## 10. Gate for building organizations (W4 part A)

Build the organization shell only if, after W2+W3 have been live for 4 weeks, **at least one of**: (a) ≥ 3 paying or pilot accounts own ≥ 3 team workspaces each; (b) ≥ 2 customers asked, unprompted, for one bill or one member list across workspaces; (c) a signed pilot requires org-level admin. Otherwise W4 ships only its GA items and the org design memo is parked with the evidence that was missing.

## 11. Decision memo — the shape of the model (ADR-0069 candidate)

**Question.** Keep workspace = tenant and add an optional organization above it, or make the organization the tenant and workspaces a folder below?

**Options.** A: workspace = tenant, org optional parent (chosen). B: org = tenant, workspace = sub-scope (Notion teamspaces). C: no org.

**Why A.** Every RLS policy, object key, Redis key, job row and audit chain is keyed by `tenant_id` today; A changes none of that and switches on code that exists. B would move the isolation boundary — every table, every key — before a single customer asked for an org. C is A without W4; A keeps the door open with one nullable column.

**Assumptions.** Small teams want separate workspaces per client/team more than one big space with folders. **Revisit trigger:** if W2 shows users creating one workspace and asking for shared folders instead, revisit B's *sub-scope* idea as "shared spaces" inside a workspace.
