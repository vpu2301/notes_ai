import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../api/http";
import {
  createPublicLink,
  getSharing,
  revokePublicLink,
  setVisibility,
  shareWithMember,
  unshareMember,
} from "../api/notes";
import type { NoteVisibility, SharingView } from "../api/types";
import { useToast } from "./Toaster";
import { AlertIcon, CheckIcon, CloseIcon, CopyIcon } from "./icons";

/** Full URL an outsider opens for a public link. */
export function publicLinkUrl(path: string): string {
  return `${window.location.origin}${path}`;
}

function mailtoUrl(to: string, subject: string, body: string): string {
  const q = new URLSearchParams({ subject, body });
  return `mailto:${encodeURIComponent(to)}?${q.toString().replace(/\+/g, "%20")}`;
}

/**
 * Everything about who can see a note, in one sheet: workspace
 * visibility, a public link, and sharing with a colleague by e-mail.
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
  const [email, setEmail] = useState("");
  const [notMember, setNotMember] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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

  const emailLink = async (to = "") => {
    let url = link;
    if (!url) {
      // Create the link first, then hand off to the mail client.
      setBusy(true);
      try {
        const v = await createPublicLink(noteId);
        setView(v);
        url = v.public_link ? publicLinkUrl(v.public_link.path) : null;
      } catch (err) {
        setError(errorMessage(err));
        return;
      } finally {
        setBusy(false);
      }
    }
    if (!url) return;
    window.location.href = mailtoUrl(to, subject, `Here is the note "${subject}":\n\n${url}\n`);
  };

  const onShare = async (e: FormEvent) => {
    e.preventDefault();
    const addr = email.trim();
    if (!addr) return;
    setNotMember(null);
    setBusy(true);
    setError(null);
    try {
      setView(await shareWithMember(noteId, addr));
      setEmail("");
      toast.success(`Shared with ${addr}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && err.code === "not_a_member") {
        setNotMember(addr);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const canManage = view?.can_manage ?? false;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Share note">
        <div className="modal-h">
          <h2>Share “{subject}”</h2>
          <p>Decide who can see this note.</p>
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
                      <button className="btn ghost sm" onClick={() => void emailLink()} disabled={busy}>
                        Email link…
                      </button>
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

              {/* ── share with a person ────────────────────────────── */}
              <form className="field" onSubmit={(e) => void onShare(e)}>
                <span className="label">Share with a colleague</span>
                <div className="share-link-row">
                  <input
                    className="input"
                    type="email"
                    placeholder="name@company.com"
                    value={email}
                    disabled={busy || !canManage}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setNotMember(null);
                    }}
                  />
                  <button className="btn primary sm" type="submit" disabled={busy || !canManage || !email.trim()}>
                    Share
                  </button>
                </div>
                {notMember && (
                  <div className="banner banner-warn">
                    <AlertIcon size={15} />
                    <span className="grow">
                      {notMember} isn’t in your workspace. You can email them a link instead.
                    </span>
                    <button className="btn sm" type="button" onClick={() => void emailLink(notMember)}>
                      Email a link
                    </button>
                  </div>
                )}
                <span className="help">They get a notification and an email, and can read the note.</span>
              </form>

              {view.shared_with.length > 0 && (
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
