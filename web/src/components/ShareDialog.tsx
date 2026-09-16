import {
  useCallback,
  useEffect,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { errorMessage } from "../api/http";
import {
  createPublicLink,
  getSharing,
  revokePublicLink,
  setVisibility,
  shareByEmail,
  unshareMember,
} from "../api/notes";
import type { NoteVisibility, ShareEmailOutcome, SharingView } from "../api/types";
import { useToast } from "./Toaster";
import { AlertIcon, CheckIcon, CloseIcon, CopyIcon, MailIcon } from "./icons";

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
export function ShareDialog({
  noteId,
  noteTitle,
  onClose,
}: {
  noteId: string;
  noteTitle: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const [view, setView] = useState<SharingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

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

  const copyLink = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — select the link and copy it by hand.");
    }
  };

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
      const result = await shareByEmail(noteId, { recipients: to, message });
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

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Share note">
        <div className="modal-h">
          <h2>Share “{subject}”</h2>
          <p>Send it to people, or decide who can see it.</p>
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
              {/* ── send it ────────────────────────────────────────── */}
              <form className="field" onSubmit={(e) => void send(e)}>
                <span className="label">Send to</span>
                <div className="chip-input" onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement | null)?.focus()}>
                  {recipients.map((address) => (
                    <span className="recipient-chip" key={address.toLowerCase()}>
                      {address}
                      <button
                        type="button"
                        aria-label={`Remove ${address}`}
                        disabled={busy}
                        onClick={() =>
                          setRecipients((current) => current.filter((r) => r !== address))
                        }
                      >
                        <CloseIcon size={11} />
                      </button>
                    </span>
                  ))}
                  <input
                    type="email"
                    multiple
                    aria-label="E-mail address"
                    placeholder={recipients.length ? "" : "name@company.com"}
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

                <textarea
                  className="textarea share-message"
                  rows={3}
                  placeholder="Add a message (optional)"
                  aria-label="Message"
                  value={message}
                  disabled={busy || !canManage}
                  maxLength={1000}
                  onChange={(e) => setMessage(e.target.value)}
                />

                <div className="row-actions">
                  <button className="btn primary sm" type="submit" disabled={busy || !canManage || !readyToSend}>
                    <MailIcon size={13} /> {busy ? "Sending…" : "Send"}
                  </button>
                  <span className="help grow">
                    People in your workspace get access to the note. Anyone else gets a link
                    they can open without signing in.
                  </span>
                </div>

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

              {/* ── visibility ─────────────────────────────────────── */}
              <div className="field">
                <span className="label">In the workspace</span>
                <div className="seg" role="group" aria-label="Visibility">
                  {(
                    [
                      ["private", "Only me and people I share with"],
                      ["workspace", "Everyone in the workspace"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className="seg-opt"
                      aria-pressed={view.visibility === value}
                      disabled={busy || !canManage}
                      onClick={() =>
                        view.visibility !== value &&
                        void run(() => setVisibility(noteId, value as NoteVisibility))
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* ── public link ────────────────────────────────────── */}
              <div className="field">
                <span className="label">Anyone with the link</span>
                {link ? (
                  <>
                    <div className="share-link-row">
                      <input className="input mono" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
                      <button className="btn sm" onClick={() => void copyLink()} title="Copy link">
                        {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />} {copied ? "Copied" : "Copy"}
                      </button>
                    </div>
                    <div className="row-actions">
                      {canManage && (
                        <button
                          className="btn ghost sm danger-text"
                          disabled={busy}
                          onClick={() => void run(() => revokePublicLink(noteId), "Link turned off")}
                        >
                          Turn off link
                        </button>
                      )}
                      <span className="help grow right">
                        {view.public_link?.view_count
                          ? `Opened ${view.public_link.view_count} time${view.public_link.view_count === 1 ? "" : "s"}`
                          : "Not opened yet"}
                      </span>
                    </div>
                  </>
                ) : (
                  <div className="row-actions">
                    <button
                      className="btn sm"
                      disabled={busy || !canManage}
                      onClick={() => void run(() => createPublicLink(noteId), "Public link created")}
                    >
                      Create public link
                    </button>
                    <span className="help">Anyone who has it can read the note, without signing in.</span>
                  </div>
                )}
              </div>

              {view.shared_with.length > 0 && (
                <div className="field">
                  <span className="label">People with access</span>
                  <ul className="share-people" aria-label="People with access">
                    {view.shared_with.map((m) => (
                      <li key={m.sub}>
                        <span className="share-person">
                          <span className="row-name">{m.display_name || m.email}</span>
                          <span className="help">{m.email}</span>
                        </span>
                        {canManage && (
                          <button
                            className="icon-btn"
                            aria-label={`Remove ${m.email}`}
                            title="Remove"
                            disabled={busy}
                            onClick={() => void run(() => unshareMember(noteId, m.sub))}
                          >
                            <CloseIcon size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
          {!view && !error && <p className="help">Loading…</p>}
        </div>

        <div className="modal-f">
          <button className="btn" onClick={onClose}>
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
