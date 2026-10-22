import React, { useCallback, useEffect, useState, type FormEvent, useRef } from "react";
import { messageFor } from "../lib/errorCopy";
import {
  createLink,
  createPublicLink,
  getSharing,
  removeCollaborator,
  revokeLink,
  sendLink,
  revokePublicLink,
  setCollaborator,
  setTranscriptSharing,
  setVisibility,
  shareByEmail,
  shareNote,
} from "../api/notes";
import { revokeInvitation } from "../api/tenants";
import { roleLabel } from "../api/types";
import type {
  CollaboratorRole,
  LinkView,
  NotePerson,
  NoteVisibility,
  ShareEmailOutcome,
  SharingView,
} from "../api/types";
import { levelLabel } from "../lib/noteLevel";
import { useToast } from "./Toaster";
import { AlertIcon, CheckIcon, CloseIcon, CopyIcon, GlobeIcon, LockIcon, MailIcon, UsersIcon } from "./icons";
import { collabTint, speakerInitials } from "../lib/speakers";
import { PUBLIC_EXPIRY_OPTIONS, PublicLinkDialog, publicLinkUrl } from "./PublicLinkDialog";
import { Select } from "./Select";
import { Segmented } from "./Segmented";
import { CharCount, ChipResults, EMAIL_RE, EmailChips, useEmailChips, type ChipResult } from "./EmailChips";
import { ApiError } from "../api/http";

const EXPIRY_OPTIONS = [7, 30, 90, 180] as const;

function opened(link: LinkView): string {
  if (!link.first_viewed_at) return "Not opened";
  return `Opened ${new Date(link.first_viewed_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
}

const MAX_SENDS = 3;

/** auth-service and note-service both cap an invitation's message here. */
const INVITE_MESSAGE_MAX = 500;

/** The chip text for one link: what the product did with it. */
export function deliveryLabel(link: LinkView): string {
  switch (link.delivery_status ?? "not_sent") {
    case "sent":
      return link.sent_at
        ? `Sent ${new Date(link.sent_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`
        : "Sent";
    case "failed":
      return "Failed";
    case "suppressed":
      return "Opted out";
    default:
      return "Not sent";
  }
}

/** A label from an address when the sender left the label empty: "tom @ client.com". */
export function labelFromEmail(email: string): string {
  const [local, domain] = email.trim().split("@");
  return domain ? `${local} @ ${domain}` : email.trim();
}

const ROLE_OPTIONS: { value: CollaboratorRole; label: string }[] = [
  { value: "view", label: "Can view" },
  { value: "comment", label: "Can comment" },
  { value: "edit", label: "Can edit" },
];

/** Why a person can open the note, in a few words. */
function personRole(p: NotePerson): string {
  if (p.source === "author") return "Author";
  if (p.source === "workspace_role") return `${levelLabel(p.level)} · ${roleLabel(p.membership_role)}`;
  return levelLabel(p.level);
}

/** "Shared with Anna", "Invited 2 people", or both. */
export function inviteSummary(granted: string[], invited: string[]): string {
  const part = (verb: string, list: string[]) =>
    list.length === 1 ? `${verb} ${list[0]}` : `${verb} ${list.length} people`;
  return [granted.length ? part("Shared with", granted) : "", invited.length ? part("Invited", invited) : ""]
    .filter(Boolean)
    .join(" · ");
}

/** Share sheet: people by role, pending invitations, general access, links. */
export interface ShareOwner {
  name: string;
  email: string;
  isMe: boolean;
}

function Avatar({ name }: { name: string }) {
  return (
    <span className="speaker-avatar share-avatar collab-avatar" style={{ "--tint": collabTint(name) } as React.CSSProperties} aria-hidden="true">
      {speakerInitials(name)}
    </span>
  );
}

export function ShareDialog({
  noteId,
  noteTitle,
  tenantId = null,
  meSub,
  owner,
  initialFocus,
  onClose,
}: {
  noteId: string;
  noteTitle: string;
  /** The active workspace: a non-member is invited into it as a guest of this note. */
  tenantId?: string | null;
  /** The signed-in person, marked "(you)" in the list. */
  meSub?: string;
  /** The note's author, shown when the server lists nobody (an older server). */
  owner?: ShareOwner;
  /** Which form gets focus once the sheet has loaded. */
  initialFocus?: "people" | "client";
  onClose: () => void;
}) {
  const toast = useToast();
  const root = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<SharingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  // The client link form.
  const [clientLabel, setClientLabel] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientMessage, setClientMessage] = useState("");
  const [clientDays, setClientDays] = useState<(typeof EXPIRY_OPTIONS)[number]>(90);
  const [newLink, setNewLink] = useState<LinkView | null>(null);
  const [linkFormOpen, setLinkFormOpen] = useState(initialFocus === "client");
  // How long the next public link lives; 0 = never.
  const [publicDays, setPublicDays] = useState<(typeof PUBLIC_EXPIRY_OPTIONS)[number]>(0);
  const [copiedLink, setCopiedLink] = useState<string | null>(null);
  // The public link's own modal, opened when the link is made.
  const [publicOpen, setPublicOpen] = useState(false);

  // People: invite by role.
  const invitees = useEmailChips();
  const [role, setRole] = useState<CollaboratorRole>("view");
  const [inviteMessage, setInviteMessage] = useState("");
  const [inviteResults, setInviteResults] = useState<ChipResult[]>([]);

  // Send a link: a read-only recipient link by e-mail.
  const recipients = useEmailChips();
  const [message, setMessage] = useState("");
  const [failures, setFailures] = useState<ShareEmailOutcome[]>([]);

  useEffect(() => {
    let live = true;
    getSharing(noteId)
      .then((v) => live && setView(v))
      .catch((err) => live && setError(messageFor(err)));
    return () => {
      live = false;
    };
  }, [noteId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = useCallback(
    async (work: () => Promise<SharingView>, done?: string) => {
      setBusy(true);
      setError(null);
      try {
        setView(await work());
        if (done) toast.success(done);
      } catch (err) {
        setError(messageFor(err));
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const subject = noteTitle.trim() || "A note";
  const link = view?.public_link ? publicLinkUrl(view.public_link.path) : null;
  const canManage = view?.can_manage ?? false;

  // ── people ────────────────────────────────────────────────────────

  /** Members get the role now; anyone else is invited as a guest of this note (auth-service mails them). */
  const invitePeople = async (e: FormEvent) => {
    e.preventDefault();
    const to = invitees.collect();
    if (!to) return;
    setBusy(true);
    setError(null);
    setInviteResults([]);
    const granted: string[] = [];
    const invited: string[] = [];
    const failed: string[] = [];
    const results: ChipResult[] = [];
    let latest: SharingView | null = null;
    for (const email of to) {
      try {
        const outcome = await shareNote(noteId, tenantId, { email, role, message: inviteMessage.trim() });
        if (outcome.kind === "granted") {
          granted.push(email);
          latest = outcome.sharing;
          results.push({ email, ok: true, text: `Has access · ${levelLabel(role).toLowerCase()}` });
        } else {
          invited.push(email);
          results.push({ email, ok: true, text: "Invited — they'll sign in to see this note" });
        }
      } catch (err) {
        failed.push(email);
        results.push({ email, ok: false, text: `Did not get access — ${shareRefusal(err)}` });
      }
    }
    try {
      // Pending invitations only show on a fresh read.
      setView(invited.length || !latest ? await getSharing(noteId) : latest);
    } catch {
      if (latest) setView(latest);
    }
    invitees.setChips(failed);
    invitees.setDraft("");
    setInviteResults(results);
    if (granted.length || invited.length) {
      if (!failed.length) setInviteMessage("");
      toast.success(inviteSummary(granted, invited));
    }
    setBusy(false);
  };

  const changeRole = (p: NotePerson, next: CollaboratorRole) =>
    void run(() => setCollaborator(noteId, p.sub, next), `${p.display_name || p.email} ${levelLabel(next).toLowerCase()}`);

  const removePerson = (p: NotePerson) =>
    void run(async () => {
      await removeCollaborator(noteId, p.sub);
      return getSharing(noteId);
    }, `${p.display_name || p.email} no longer has access`);

  const revokePending = (invitationId: string) => {
    if (!tenantId) return;
    void run(async () => {
      await revokeInvitation(tenantId, invitationId);
      return getSharing(noteId);
    }, "Invitation revoked");
  };

  // ── send a link ───────────────────────────────────────────────────

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const to = recipients.collect();
    if (!to) return;
    setBusy(true);
    setError(null);
    setFailures([]);
    try {
      const result = await shareByEmail(noteId, {
        recipients: to,
        message,
        expires_in_days: clientDays,
        role: "view",
        mode: "link",
      });
      setView(result.sharing);
      const sent = result.results.filter((r) => r.status === "sent");
      setFailures(result.results.filter((r) => r.status !== "sent"));
      recipients.setChips(sent.length === result.results.length ? [] : failedAddresses(result.results));
      recipients.setDraft("");
      const only = sent.length === 1 ? sent[0] : undefined;
      if (sent.length) {
        setMessage("");
        toast.success(only ? `Sent to ${only.email}` : `Sent to ${sent.length} people`);
      }
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  // ── client links ──────────────────────────────────────────────────

  const clientLinks = (view?.links ?? []).filter((l) => l.kind === "recipient");
  // Older servers send no constraints.
  const rules = view?.constraints;
  const externalOff = rules ? !rules.external_links_enabled : false;
  const publicOff = rules ? !rules.public_links_enabled : false;
  const expiryOptions = EXPIRY_OPTIONS.filter((d) => !rules || d <= rules.max_link_days);
  const emailRequired = rules?.verified_recipients_required ?? false;
  useEffect(() => {
    const at = view?.public_link?.expires_at;
    if (!view?.public_link) return;
    if (!at) {
      setPublicDays(0);
      return;
    }
    const days = Math.round((new Date(at).getTime() - new Date(view.public_link.created_at).getTime()) / 86_400_000);
    const nearest = PUBLIC_EXPIRY_OPTIONS.reduce((best, d) => (d > 0 && Math.abs(d - days) < Math.abs(best - days) ? d : best), 180 as (typeof PUBLIC_EXPIRY_OPTIONS)[number]);
    setPublicDays(nearest);
  }, [view?.public_link]);

  useEffect(() => {
    if (rules && clientDays > rules.max_link_days) {
      setClientDays((expiryOptions[expiryOptions.length - 1] ?? 30) as (typeof EXPIRY_OPTIONS)[number]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rules?.max_link_days]);

  const copyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedLink(key);
      window.setTimeout(() => setCopiedLink(null), 1500);
    } catch {
      toast.error("Could not copy — select the link and copy it by hand.");
    }
  };

  const createClientLink = async (e: FormEvent, send = false) => {
    e.preventDefault();
    const email = clientEmail.trim();
    const label = clientLabel.trim() || (email ? labelFromEmail(email) : "");
    if (!label) return;
    if (email && !EMAIL_RE.test(email)) {
      setError(`“${email}” doesn’t look like an e-mail address.`);
      return;
    }
    if (send && !email) {
      setError("Add the recipient's e-mail address to send the link.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const link = await createLink(noteId, {
        label,
        recipient_email: email || undefined,
        expires_in_days: clientDays,
        send,
        personal_message: send && clientMessage.trim() ? clientMessage.trim() : undefined,
        lang: send ? navigator.language.slice(0, 2) : undefined,
        source: "dialog",
      });
      setNewLink(link);
      setClientLabel("");
      setClientEmail("");
      setClientMessage("");
      setView(await getSharing(noteId));
      toast.success(send ? (link.delivery_status === "sent" ? `Sent to ${email}` : "Link created, but the e-mail did not go out") : "Link created");
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const resendClientLink = async (link: LinkView) => {
    setBusy(true);
    setError(null);
    try {
      const next = await sendLink(noteId, link.id, { lang: navigator.language.slice(0, 2) });
      setView(await getSharing(noteId));
      toast.success(next.delivery_status === "sent" ? "Sent" : "The e-mail did not go out");
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const revokeClientLink = async (link: LinkView) => {
    setBusy(true);
    setError(null);
    try {
      await revokeLink(noteId, link.id);
      if (newLink?.id === link.id) setNewLink(null);
      setView(await getSharing(noteId));
      toast.success("Link turned off");
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const people = view?.people ?? [];
  const pending = view?.pending ?? [];
  const personal = view?.workspace_kind === "personal";

  const visibility: NoteVisibility = view?.visibility ?? "private";
  const changeVisibility = (value: NoteVisibility) => {
    if (!view || value === view.visibility) return;
    void run(() => setVisibility(noteId, value));
  };
  const accessText =
    visibility === "workspace"
      ? "Members of the workspace can edit it; viewers can comment."
      : "Only you and the people you share it with can open it.";
  const togglePublicLink = (on: boolean) =>
    on
      ? void run(async () => {
          const next = await createPublicLink(noteId, publicDays || undefined);
          setPublicOpen(true);
          return next;
        })
      : void run(() => revokePublicLink(noteId), "Public link turned off");

  /** Expiry is set at mint time: changing it mints a new link and the old one stops working. */
  const renewPublicLink = (days: (typeof PUBLIC_EXPIRY_OPTIONS)[number]) => {
    setPublicDays(days);
    if (!link) return;
    void run(async () => {
      await revokePublicLink(noteId);
      return createPublicLink(noteId, days || undefined);
    }, "New link created — the previous one no longer works");
  };
  const publicExpiry = view?.public_link?.expires_at
    ? `Expires ${new Date(view.public_link.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`
    : "Never expires";

  const copyFooterLink = async () => {
    const url = link ?? `${window.location.origin}/notes/${noteId}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — select the link and copy it by hand.");
    }
  };

  const loaded = view !== null;
  useEffect(() => {
    if (!loaded || !initialFocus) return;
    const selector = initialFocus === "client" ? 'input[aria-label="Recipient label"]' : 'input[aria-label="E-mail address"]';
    const el = root.current?.querySelector<HTMLInputElement>(selector);
    el?.focus();
    el?.scrollIntoView?.({ block: "center" });
  }, [loaded, initialFocus]);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Share note" ref={root}>
        <div className="modal-h">
          <h2>Share “{subject}”</h2>
          <button className="icon-btn modal-x" aria-label="Close" onClick={onClose}>
            <CloseIcon size={14} />
          </button>
        </div>

        <div className="modal-b">
          {error && (
            <div className="banner banner-danger" role="alert">
              <AlertIcon size={15} />
              <span className="grow">{error}</span>
            </div>
          )}

          {view && (
            <>
              {/* ── people ───────────────────────────────────────────── */}
              <section className="share-sec" aria-label="People">
                {canManage && (
                  <form className="share-sec" onSubmit={(e) => void invitePeople(e)}>
                    <EmailChips
                      box={invitees}
                      label="Invite people"
                      placeholder="Add people by e-mail"
                      disabled={busy}
                      className="share-people-box"
                    />
                    {invitees.composing && (
                      <>
                        <div className="share-send-row">
                          <Select label="Role" value={role} disabled={busy} options={ROLE_OPTIONS} onChange={setRole} />
                          <span className="help grow">
                            People in your workspace get access now; others get an e-mail and sign in to see this note.
                          </span>
                        </div>
                        <textarea
                          className="textarea"
                          rows={2}
                          placeholder="Add a message (optional)"
                          aria-label="Invitation message"
                          value={inviteMessage}
                          disabled={busy}
                          maxLength={INVITE_MESSAGE_MAX}
                          onChange={(e) => setInviteMessage(e.target.value)}
                        />
                        <div className="share-send-row">
                          <CharCount value={inviteMessage} max={INVITE_MESSAGE_MAX} />
                          <span className="grow" />
                          <button className="btn moss" type="submit" disabled={busy || !invitees.ready}>
                            {busy ? "Sharing…" : "Share"}
                          </button>
                        </div>
                      </>
                    )}
                    <ChipResults results={inviteResults} label="Share results" />
                  </form>
                )}

                <h3 className="share-h">Who has access</h3>
                <ul className="share-people" aria-label="Who has access">
                  {visibility === "workspace" && !personal && (
                    <li>
                      <span className="share-avatar share-avatar-ws" aria-hidden="true">
                        <UsersIcon size={15} />
                      </span>
                      <span className="share-person">
                        <span className="row-name">Everyone in the workspace</span>
                        <span className="help">Members can edit · viewers can comment</span>
                      </span>
                      <span className="share-role">Can edit</span>
                    </li>
                  )}
                  {people.length === 0 && owner && (
                    <li>
                      <Avatar name={owner.name || owner.email} />
                      <span className="share-person">
                        <span className="row-name">
                          {owner.name || owner.email}
                          {owner.isMe && " (you)"}
                        </span>
                        {owner.name && owner.email && <span className="help">{owner.email}</span>}
                      </span>
                      <span className="share-role">Author</span>
                    </li>
                  )}
                  {people.map((p) => {
                    const name = p.display_name || p.email;
                    const changeable = canManage && p.can_change && p.source === "collaborator";
                    return (
                      <li key={p.sub}>
                        <Avatar name={name} />
                        <span className="share-person">
                          <span className="row-name">
                            {name}
                            {p.sub === meSub && " (you)"}
                            {p.membership_role === "guest" && <span className="chip guest-badge">Guest</span>}
                          </span>
                          {p.display_name && p.email && <span className="help">{p.email}</span>}
                        </span>
                        {changeable ? (
                          <span className="share-actions">
                            <Select
                              label={`Role for ${name}`}
                              variant="text"
                              value={p.level as CollaboratorRole}
                              disabled={busy}
                              options={ROLE_OPTIONS}
                              onChange={(next) => changeRole(p, next)}
                            />
                            <button className="icon-btn" aria-label={`Remove ${name}`} title="Remove" disabled={busy} onClick={() => removePerson(p)}>
                              <CloseIcon size={13} />
                            </button>
                          </span>
                        ) : (
                          <span className="share-role">{personRole(p)}</span>
                        )}
                      </li>
                    );
                  })}
                </ul>

                {canManage && pending.length > 0 && (
                  <>
                    <h3 className="share-h">Pending</h3>
                    <ul className="share-people" aria-label="Pending invitations">
                      {pending.map((inv) => (
                        <li key={inv.invitation_id}>
                          <Avatar name={inv.email_masked} />
                          <span className="share-person">
                            <span className="row-name">{inv.email_masked}</span>
                            <span className="help">
                              {levelLabel(inv.note_role)} · expires {new Date(inv.expires_at).toLocaleDateString()}
                            </span>
                          </span>
                          {tenantId && (
                            <button
                              type="button"
                              className="btn ghost sm"
                              aria-label={`Revoke invitation for ${inv.email_masked}`}
                              disabled={busy}
                              onClick={() => revokePending(inv.invitation_id)}
                            >
                              Revoke
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              {/* ── general access ─────────────────────────────────── */}
              <section className="share-sec" aria-label="General access">
                <h3 className="share-h">General access</h3>
                <div className="share-access">
                  <span className={`share-access-icon ${visibility}`} aria-hidden="true">
                    {visibility === "workspace" ? <UsersIcon size={16} /> : <LockIcon size={16} />}
                  </span>
                  <div className="share-access-body">
                    {/* A personal workspace has nobody else in it: no choice to make. */}
                    {canManage && !personal && (
                      <Segmented<NoteVisibility>
                        label="General access"
                        value={visibility}
                        options={[
                          { value: "private", label: "Private" },
                          { value: "workspace", label: "Workspace" },
                        ]}
                        onChange={changeVisibility}
                      />
                    )}
                    <span className="help">{accessText}</span>
                  </div>
                </div>
                {canManage && view.transcript_shared !== undefined && (
                  <label className="chk-row share-transcript">
                    <input
                      type="checkbox"
                      className="chk"
                      checked={view.transcript_shared}
                      disabled={busy}
                      onChange={(e) => {
                        const shared = e.target.checked;
                        void run(
                          () => setTranscriptSharing(noteId, shared),
                          shared ? "Transcript and audio included" : "Transcript and audio no longer included",
                        );
                      }}
                    />
                    <span className="share-person">
                      <span>Include transcript and audio for viewers and commenters</span>
                      <span className="help">Editors and workspace members always see them.</span>
                    </span>
                  </label>
                )}
                {(link || (canManage && !publicOff)) && (
                  <div className="share-access">
                    <span className="share-access-icon link" aria-hidden="true">
                      <GlobeIcon size={16} />
                    </span>
                    <div className="share-access-body">
                      {canManage ? (
                        <label className="chk-row">
                          <input
                            type="checkbox"
                            className="chk"
                            checked={!!link}
                            disabled={busy || (!link && publicOff)}
                            onChange={(e) => togglePublicLink(e.target.checked)}
                          />
                          <span>Anyone with the link</span>
                        </label>
                      ) : (
                        <span>Anyone with the link</span>
                      )}
                      <span className="help">
                        {link
                          ? "Can read and download it, without signing in — but not respond."
                          : "Off. Turn on to let anyone with the link read it without signing in."}
                      </span>
                      {link && canManage && (
                        <>
                          <Select
                            label="Public link expires"
                            value={publicDays}
                            disabled={busy}
                            options={PUBLIC_EXPIRY_OPTIONS.map((d) => ({
                              value: d,
                              label: d === 0 ? "Permanent — never expires" : `Limited — ${d} days`,
                            }))}
                            onChange={renewPublicLink}
                          />
                          <span className="help">
                            {publicExpiry} ·{" "}
                            {view.public_link?.view_count
                              ? `opened ${view.public_link.view_count} time${view.public_link.view_count === 1 ? "" : "s"}`
                              : "not opened yet"}
                            {" · changing the duration creates a new link"}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </section>

              {/* ── send a link ────────────────────────────────────────── */}
              {canManage && !externalOff && (
                <section className="share-sec" aria-label="Send a link">
                  <h3 className="share-h">Send a link</h3>
                  <form className="share-sec" onSubmit={(e) => void send(e)}>
                    <EmailChips
                      box={recipients}
                      label="E-mail address"
                      placeholder="Send a read-only link by e-mail"
                      disabled={busy}
                      className="share-people-box"
                    />
                    {recipients.composing && (
                      <>
                        <textarea
                          className="textarea"
                          rows={3}
                          placeholder="Add a message (optional)"
                          aria-label="Message"
                          value={message}
                          disabled={busy}
                          maxLength={1000}
                          onChange={(e) => setMessage(e.target.value)}
                        />
                        <div className="share-send-row">
                          <Select
                            label="Link expires after"
                            value={clientDays}
                            disabled={busy}
                            options={expiryOptions.map((d) => ({ value: d, label: `Link expires in ${d} days` }))}
                            onChange={setClientDays}
                          />
                          <span className="help grow">
                            Each person gets their own link: they can read, download the PDF and confirm or dispute action
                            items without an account, and you see when they open it.
                          </span>
                          <button className="btn moss" type="submit" disabled={busy || !recipients.ready}>
                            <MailIcon size={13} /> {busy ? "Sending…" : "Send"}
                          </button>
                        </div>
                      </>
                    )}
                    {failures.length > 0 && (
                      <div className="banner banner-warn">
                        <AlertIcon size={15} />
                        <span className="grow">
                          {failures.map((f) => f.email).join(", ")} did not go out —{" "}
                          {failures.every((f) => f.status === "rejected")
                            ? "the address was refused. Check the spelling."
                            : "the mail server did not take it. Try again in a moment."}
                        </span>
                      </div>
                    )}
                  </form>

                  <div className="share-more">
                    <button type="button" className="btn ghost sm" aria-expanded={linkFormOpen} onClick={() => setLinkFormOpen((o) => !o)}>
                      {linkFormOpen ? "Hide" : "Create a link without sending…"}
                    </button>
                    {linkFormOpen && (
                      <form className="share-link-form" onSubmit={(e) => void createClientLink(e, false)}>
                        <input
                          className="input"
                          aria-label="Recipient label"
                          placeholder="Who is it for? e.g. Tom @ Client"
                          value={clientLabel}
                          disabled={busy}
                          maxLength={120}
                          onChange={(e) => setClientLabel(e.target.value)}
                        />
                        <input
                          className="input"
                          type="email"
                          aria-label="Recipient e-mail"
                          placeholder={emailRequired ? "Their e-mail" : "Their e-mail (optional)"}
                          value={clientEmail}
                          disabled={busy}
                          onChange={(e) => setClientEmail(e.target.value)}
                        />
                        <button
                          className="btn sm"
                          type="submit"
                          disabled={busy || (!clientLabel.trim() && !clientEmail.trim()) || (emailRequired && !clientEmail.trim())}
                        >
                          Create link only
                        </button>
                        {emailRequired && (
                          <span className="help share-link-form-help">Recipients must confirm a code sent to their e-mail before they can respond.</span>
                        )}
                        {newLink && (
                          <div className="share-link-row share-link-form-row">
                            <input
                              className="input mono"
                              readOnly
                              aria-label="Client link"
                              value={publicLinkUrl(newLink.path)}
                              onFocus={(e) => e.currentTarget.select()}
                            />
                            <button type="button" className="btn sm" onClick={() => void copyText(publicLinkUrl(newLink.path), newLink.id)} title="Copy link">
                              {copiedLink === newLink.id ? <CheckIcon size={13} /> : <CopyIcon size={13} />} {copiedLink === newLink.id ? "Copied" : "Copy"}
                            </button>
                          </div>
                        )}
                      </form>
                    )}
                  </div>

                  {clientLinks.length > 0 && (
                    <ul className="share-people" aria-label="Links">
                      {clientLinks.map((l) => (
                        <li key={l.id}>
                          <Avatar name={l.label || l.recipient_email || "Link"} />
                          <span className="share-person">
                            <span className="row-name">
                              {l.label || l.recipient_email || "Link"}
                              {l.cta_clicked_at && <span className="cta-dot" title="Clicked “create your own workspace”" />}
                            </span>
                            <span className="share-meta">
                              <span className={`chip delivery-${l.delivery_status ?? "not_sent"}`}>{deliveryLabel(l)}</span>
                              <span className="help">{opened(l)}</span>
                              {(l.response_count ?? 0) > 0 && <span className="help">· Responded ({l.response_count})</span>}
                              {l.expires_at && <span className="help">· expires {new Date(l.expires_at).toLocaleDateString()}</span>}
                            </span>
                          </span>
                          <span className="share-actions">
                            {l.recipient_email && l.delivery_status !== "suppressed" && (l.send_count ?? 0) < MAX_SENDS && (
                              <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void resendClientLink(l)}>
                                {l.delivery_status === "failed" ? "Retry" : (l.send_count ?? 0) > 0 ? "Resend" : "Send"}
                              </button>
                            )}
                            <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void copyText(publicLinkUrl(l.path), l.id)}>
                              {copiedLink === l.id ? "Copied" : "Copy"}
                            </button>
                            <button
                              type="button"
                              className="icon-btn"
                              aria-label={`Turn off link for ${l.label || l.recipient_email || "recipient"}`}
                              title="Turn off"
                              disabled={busy}
                              onClick={() => void revokeClientLink(l)}
                            >
                              <CloseIcon size={13} />
                            </button>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </>
          )}
          {!view && !error && <p className="help">Loading…</p>}
        </div>

        <div className="modal-f share-f">
          <button className="btn moss-outline" onClick={() => void copyFooterLink()} title={link ? "Copy the public link" : "Copy the link to this note"}>
            {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} {copied ? "Copied" : "Copy link"}
          </button>
          <span className="grow" />
          <button className="btn moss" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
      {publicOpen && view?.public_link && (
        <PublicLinkDialog
          noteId={noteId}
          noteTitle={noteTitle}
          link={view.public_link}
          onChange={setView}
          onClose={() => setPublicOpen(false)}
        />
      )}
    </div>
  );
}

/** The addresses worth keeping in the box so the sender can retry them. */
function failedAddresses(results: ShareEmailOutcome[]): string[] {
  return results.filter((r) => r.status !== "sent").map((r) => r.email);
}

/** Why one address did not get access, in the sender's terms. */
function shareRefusal(err: unknown): string {
  if (err instanceof ApiError && err.code === "not_a_member") {
    // `can_invite: false`: the workspace's sharing settings keep outsiders out.
    return err.extra<boolean>("can_invite") === false
      ? "this workspace's sharing settings don't allow inviting people from outside."
      : "not in this workspace, and they can't be invited from here.";
  }
  return messageFor(err);
}
