import React, {
  useCallback,
  useEffect,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { errorMessage } from "../api/http";
import {
  createLink,
  createPublicLink,
  getSharing,
  revokeLink,
  sendLink,
  revokePublicLink,
  setVisibility,
  shareByEmail,
  unshareMember,
} from "../api/notes";
import type { LinkView, NoteVisibility, ShareEmailOutcome, SharingView } from "../api/types";
import { useToast } from "./Toaster";
import { AlertIcon, CheckIcon, CloseIcon, CopyIcon, GlobeIcon, LockIcon, MailIcon, UsersIcon } from "./icons";
import { speakerInitials, speakerTint } from "../lib/speakers";
import { Select } from "./Select";

const EXPIRY_OPTIONS = [7, 30, 90, 180] as const;
/** Public links may also live forever (0 = never). */
const PUBLIC_EXPIRY_OPTIONS = [0, 7, 30, 90, 180] as const;

function opened(link: LinkView): string {
  if (!link.first_viewed_at) return "Not opened";
  return `Opened ${new Date(link.first_viewed_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
}

const MAX_SENDS = 3;

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

/** Full URL an outsider opens for a public link. */
export function publicLinkUrl(path: string): string {
  return `${window.location.origin}${path}`;
}

/** Loose shape check — the real test is whether a relay accepts it. */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Everything about who can see a note, in one sheet: who to send it to,
 * workspace visibility, and a public link.
 *
 * Sending is the sheet's job, not the mail client's. The old "Email
 * link…" button navigated to a `mailto:` URL, which left the sender
 * staring at an unstyled draft they still had to send — and, on macOS,
 * at whatever Mail.app happened to have open, old attachment and all.
 * Here the addresses are picked, the message is typed, and the server
 * sends the real mail.
 */
export interface ShareOwner {
  name: string;
  email: string;
  isMe: boolean;
}

function Avatar({ name }: { name: string }) {
  return (
    <span className="speaker-avatar share-avatar" style={{ "--tint": speakerTint(name) } as React.CSSProperties} aria-hidden="true">
      {speakerInitials(name)}
    </span>
  );
}

export function ShareDialog({
  noteId,
  noteTitle,
  owner,
  onClose,
}: {
  noteId: string;
  noteTitle: string;
  /** The note's author, shown first under "People with access". */
  owner?: ShareOwner;
  onClose: () => void;
}) {
  const toast = useToast();
  const [view, setView] = useState<SharingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  // The client link form (Sprint 19).
  const [clientLabel, setClientLabel] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientMessage, setClientMessage] = useState("");
  const [clientDays, setClientDays] = useState<(typeof EXPIRY_OPTIONS)[number]>(90);
  const [newLink, setNewLink] = useState<LinkView | null>(null);
  const [linkFormOpen, setLinkFormOpen] = useState(false);
  // How long the next public link lives; 0 = never.
  const [publicDays, setPublicDays] = useState<(typeof PUBLIC_EXPIRY_OPTIONS)[number]>(0);
  const [copiedLink, setCopiedLink] = useState<string | null>(null);

  // The compose box: confirmed addresses, plus whatever is half-typed.
  const [recipients, setRecipients] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [failures, setFailures] = useState<ShareEmailOutcome[]>([]);

  useEffect(() => {
    let live = true;
    getSharing(noteId)
      .then((v) => live && setView(v))
      .catch((err) => live && setError(errorMessage(err)));
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
        setError(errorMessage(err));
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const subject = noteTitle.trim() || "A note";
  const link = view?.public_link ? publicLinkUrl(view.public_link.path) : null;
  const canManage = view?.can_manage ?? false;

  // ── the compose box ───────────────────────────────────────────────

  /** Turn what is typed into a chip. Returns false if it is not an address. */
  const commitDraft = (raw = draft): boolean => {
    const address = raw.trim().replace(/[,;]+$/, "");
    if (!address) return true;
    if (!EMAIL_RE.test(address)) {
      setDraftError(`“${address}” doesn’t look like an e-mail address.`);
      return false;
    }
    setDraftError(null);
    setDraft("");
    setRecipients((current) =>
      current.some((r) => r.toLowerCase() === address.toLowerCase()) ? current : [...current, address],
    );
    return true;
  };

  const onDraftKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === ";" || e.key === " ") {
      // Space commits too: pasting a list separated by spaces is common,
      // and no e-mail address anybody types here contains one.
      if (draft.trim()) {
        e.preventDefault();
        commitDraft();
      }
      return;
    }
    const last = recipients[recipients.length - 1];
    if (e.key === "Backspace" && !draft && last) {
      // Backspace on an empty box edits the last chip rather than
      // silently deleting it — a typo is the usual reason to press it.
      setRecipients((current) => current.slice(0, -1));
      setDraft(last);
    }
  };

  /** A pasted list ("a@x.com, b@y.com") becomes chips, not one bad chip. */
  const onPaste = (e: ReactClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text");
    if (!/[,;\s]/.test(text)) return;
    e.preventDefault();
    const parts = text.split(/[,;\s]+/).filter(Boolean);
    let ok = true;
    for (const part of parts) ok = commitDraft(part) && ok;
    if (!ok) setDraft("");
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!commitDraft()) return;
    // commitDraft's setState has not landed yet, so fold the last typed
    // address in by hand rather than sending one recipient short.
    const typed = draft.trim().replace(/[,;]+$/, "");
    const all = typed && EMAIL_RE.test(typed) ? [...recipients, typed] : recipients;
    const to = all.filter((a, i) => all.findIndex((b) => b.toLowerCase() === a.toLowerCase()) === i);
    if (!to.length) {
      setDraftError("Add at least one e-mail address.");
      return;
    }
    setBusy(true);
    setError(null);
    setFailures([]);
    try {
      const result = await shareByEmail(noteId, { recipients: to, message, expires_in_days: clientDays });
      setView(result.sharing);
      const sent = result.results.filter((r) => r.status === "sent");
      setFailures(result.results.filter((r) => r.status !== "sent"));
      setRecipients(sent.length === result.results.length ? [] : failedAddresses(result.results));
      setDraft("");
      const only = sent.length === 1 ? sent[0] : undefined;
      if (sent.length) {
        setMessage("");
        toast.success(only ? `Sent to ${only.email}` : `Sent to ${sent.length} people`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const readyToSend = recipients.length > 0 || EMAIL_RE.test(draft.trim());

  // ── client links ──────────────────────────────────────────────────

  const clientLinks = (view?.links ?? []).filter((l) => l.kind === "recipient");
  // Sprint 23: the workspace's rules. Older servers send no constraints.
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
      setError(errorMessage(err));
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
      setError(errorMessage(err));
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
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const members = view?.shared_with ?? [];
  const hasPeople = owner !== undefined || members.length > 0 || clientLinks.length > 0;
  const composing = recipients.length > 0 || draft.trim().length > 0;

  // General access, the way a file's share sheet says it: one choice.
  const accessValue: "private" | "workspace" | "link" = link ? "link" : (view?.visibility ?? "private");
  const setAccess = (value: "private" | "workspace" | "link") => {
    if (!view || value === accessValue) return;
    if (value === "link") {
      void run(() => createPublicLink(noteId, publicDays || undefined), "Anyone with the link can now open it");
      return;
    }
    void run(async () => {
      if (link) await revokePublicLink(noteId);
      return view.visibility === value ? getSharing(noteId) : setVisibility(noteId, value as NoteVisibility);
    });
  };
  const accessText = {
    private: "Only you and the people you share it with can open it.",
    workspace: "Everyone in your workspace can open it.",
    link: "Anyone with the link can read and download it, without signing in — but not respond.",
  }[accessValue];

  /** A public link's expiry can only be set when it is minted: changing
      it later mints a new link, and the old one stops working. */
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
  const AccessIcon = accessValue === "link" ? GlobeIcon : accessValue === "workspace" ? UsersIcon : LockIcon;

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

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Share note">
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
              {/* ── send ───────────────────────────────────────────── */}
              <section className="share-sec" aria-label="Send">
                <form className="share-sec" onSubmit={(e) => void send(e)}>
                  <div className="chip-input share-people-box" onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement | null)?.focus()}>
                    {recipients.map((address) => (
                      <span className="recipient-chip" key={address.toLowerCase()}>
                        {address}
                        <button
                          type="button"
                          aria-label={`Remove ${address}`}
                          disabled={busy}
                          onClick={() => setRecipients((current) => current.filter((r) => r !== address))}
                        >
                          <CloseIcon size={11} />
                        </button>
                      </span>
                    ))}
                    <input
                      type="email"
                      multiple
                      aria-label="E-mail address"
                      placeholder={recipients.length ? "" : "Add people by e-mail"}
                      value={draft}
                      disabled={busy || !canManage}
                      onChange={(e) => {
                        setDraft(e.target.value);
                        setDraftError(null);
                      }}
                      onKeyDown={onDraftKeyDown}
                      onPaste={onPaste}
                      onBlur={() => commitDraft()}
                    />
                  </div>
                  {draftError && <span className="help danger-text">{draftError}</span>}
                  {composing && (
                  <>
                  <textarea
                    className="textarea"
                    rows={3}
                    placeholder="Add a message (optional)"
                    aria-label="Message"
                    value={message}
                    disabled={busy || !canManage}
                    maxLength={1000}
                    onChange={(e) => setMessage(e.target.value)}
                  />
                  <div className="share-send-row">
                    {!externalOff && (
                      <Select
                        label="Link expires after"
                        value={clientDays}
                        disabled={busy}
                        options={expiryOptions.map((d) => ({ value: d, label: `Link expires in ${d} days` }))}
                        onChange={setClientDays}
                      />
                    )}
                    <span className="help grow">
                      {externalOff
                        ? "Workspace members get access. Sharing outside the workspace is off for this workspace."
                        : "Members get access. Anyone else gets their own link: they can read, download the PDF and confirm or dispute action items, and you see when they open it."}
                    </span>
                    <button className="btn moss" type="submit" disabled={busy || !canManage || !readyToSend}>
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

                {canManage && !externalOff && (
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
                )}
              </section>

              {/* ── people ─────────────────────────────────────────── */}
              {hasPeople && (
                <section className="share-sec">
                  <h3 className="share-h">People with access</h3>
                  <ul className="share-people" aria-label="People with access">
                    {owner && (
                      <li>
                        <Avatar name={owner.name || owner.email} />
                        <span className="share-person">
                          <span className="row-name">
                            {owner.name || owner.email}
                            {owner.isMe && " (you)"}
                          </span>
                          {owner.name && <span className="help">{owner.email}</span>}
                        </span>
                        <span className="share-role">Owner</span>
                      </li>
                    )}
                    {members.map((m) => (
                      <li key={m.sub}>
                        <Avatar name={m.display_name || m.email} />
                        <span className="share-person">
                          <span className="row-name">{m.display_name || m.email}</span>
                          {m.display_name && <span className="help">{m.email}</span>}
                        </span>
                        <span className="share-role">Member</span>
                        {canManage && (
                          <button className="icon-btn" aria-label={`Remove ${m.email}`} title="Remove" disabled={busy} onClick={() => void run(() => unshareMember(noteId, m.sub))}>
                            <CloseIcon size={13} />
                          </button>
                        )}
                      </li>
                    ))}
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
                </section>
              )}

              {/* ── general access ─────────────────────────────────── */}
              <section className="share-sec">
                <h3 className="share-h">General access</h3>
                <div className="share-access">
                  <span className={`share-access-icon ${accessValue}`} aria-hidden="true">
                    <AccessIcon size={16} />
                  </span>
                  <div className="share-access-body">
                    <Select<"private" | "workspace" | "link">
                      label="General access"
                      variant="text"
                      value={accessValue}
                      disabled={busy || !canManage}
                      options={[
                        { value: "private", label: "Restricted" },
                        { value: "workspace", label: "Everyone in the workspace" },
                        ...(!publicOff || link ? [{ value: "link" as const, label: "Anyone with the link" }] : []),
                      ]}
                      onChange={setAccess}
                    />
                    <span className="help">{accessText}</span>
                  </div>
                </div>
                {accessValue === "link" && (
                  <div className="share-access share-access-sub">
                    <span className="share-access-spacer" aria-hidden="true" />
                    <div className="share-access-body">
                      <Select
                        label="Public link expires"
                        value={publicDays}
                        disabled={busy || !canManage}
                        options={PUBLIC_EXPIRY_OPTIONS.map((d) => ({
                          value: d,
                          label: d === 0 ? "Permanent — never expires" : `Limited — ${d} days`,
                        }))}
                        onChange={renewPublicLink}
                      />
                      <span className="help">
                        {link ? `${publicExpiry} · ` : ""}
                        {view.public_link?.view_count
                          ? `opened ${view.public_link.view_count} time${view.public_link.view_count === 1 ? "" : "s"}`
                          : "not opened yet"}
                        {link && " · changing the duration creates a new link"}
                      </span>
                    </div>
                  </div>
                )}
              </section>
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
    </div>
  );
}

/** The addresses worth keeping in the box so the sender can retry them. */
function failedAddresses(results: ShareEmailOutcome[]): string[] {
  return results.filter((r) => r.status !== "sent").map((r) => r.email);
}
