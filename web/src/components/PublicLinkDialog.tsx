import { useEffect, useRef, useState } from "react";
import { createPublicLink, revokePublicLink } from "../api/notes";
import type { LinkView, SharingView } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { AlertIcon, CheckIcon, CloseIcon, CopyIcon, GlobeIcon, MailIcon } from "./icons";
import { Select } from "./Select";

/** Public links may live forever (0 = never) or a limited number of days. */
export const PUBLIC_EXPIRY_OPTIONS = [0, 7, 30, 90, 180] as const;

/** Full URL an outsider opens for a public link. */
export function publicLinkUrl(path: string): string {
  return `${window.location.origin}${path}`;
}

/** The option a live link was made with: its lifetime in whole days, 0 when it never expires. */
function daysOf(link: LinkView): number {
  if (!link.expires_at) return 0;
  return Math.round((new Date(link.expires_at).getTime() - new Date(link.created_at).getTime()) / 86_400_000);
}

/**
 * Shown right after a public link is made: the link itself, what kind it is (permanent or
 * limited), and the two things people do next — copy it or send it.
 */
export function PublicLinkDialog({
  noteId,
  noteTitle,
  link: initial,
  onChange,
  onClose,
}: {
  noteId: string;
  noteTitle: string;
  link: LinkView;
  /** Each new sharing state (a renewed or turned-off link), for whoever opened this. */
  onChange: (view: SharingView) => void;
  onClose: () => void;
}) {
  const [link, setLink] = useState(initial);
  const [days, setDays] = useState(() => daysOf(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const url = publicLinkUrl(link.path);

  // Over the share dialog: Escape closes this one only.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setCopyFailed(false);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopyFailed(true);
      inputRef.current?.select();
    }
  };

  const subject = noteTitle.trim() || "A note";
  const send = async () => {
    // The system share sheet where there is one (Mail, Messages, …), else the mail app.
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title: subject, url });
        return;
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
      }
    }
    window.location.href = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(url)}`;
  };

  const run = async (work: () => Promise<SharingView>): Promise<SharingView | null> => {
    setBusy(true);
    setError(null);
    try {
      const view = await work();
      onChange(view);
      return view;
    } catch (err) {
      setError(messageFor(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  /** Expiry is set at mint time: a new type mints a new link and the old one stops working. */
  const changeDays = async (next: number) => {
    if (next === days) return;
    setDays(next);
    setCopied(false);
    const view = await run(async () => {
      await revokePublicLink(noteId);
      return createPublicLink(noteId, next || undefined);
    });
    if (view?.public_link) setLink(view.public_link);
  };

  const turnOff = async () => {
    if (await run(() => revokePublicLink(noteId))) onClose();
  };

  const kind = link.expires_at
    ? `Limited · expires ${new Date(link.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`
    : "Permanent · never expires";

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal plink-modal" role="dialog" aria-modal="true" aria-label="Public link">
        <div className="modal-h">
          <div className="plink-head">
            <span className="plink-mark" aria-hidden="true">
              <GlobeIcon size={18} />
            </span>
            <div>
              <h2>Public link</h2>
              <p>Anyone with the link can read and download “{subject}” — no sign-in, no replies.</p>
            </div>
          </div>
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
          <div className="plink-url">
            <input
              ref={inputRef}
              className="input mono"
              readOnly
              aria-label="Public link"
              value={url}
              onFocus={(e) => e.currentTarget.select()}
            />
            <button className="btn moss" onClick={() => void copy()} disabled={busy}>
              {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} {copied ? "Copied" : "Copy"}
            </button>
          </div>
          {copyFailed && <span className="help">Could not copy — the link is selected, copy it by hand.</span>}

          <div className="plink-type">
            <Select
              label="Link type"
              value={days}
              disabled={busy}
              options={PUBLIC_EXPIRY_OPTIONS.map((d) => ({
                value: d as number,
                label: d === 0 ? "Permanent — never expires" : `Limited — ${d} days`,
              }))}
              onChange={(d) => void changeDays(d)}
            />
            <span className="help">
              {kind} ·{" "}
              {link.view_count ? `opened ${link.view_count} time${link.view_count === 1 ? "" : "s"}` : "not opened yet"}
            </span>
            <span className="help">Changing the type creates a new link; the previous one stops working.</span>
          </div>
        </div>

        <div className="modal-f">
          <button className="btn ghost plink-off" onClick={() => void turnOff()} disabled={busy}>
            Turn off link
          </button>
          <span className="grow" />
          <button className="btn" onClick={() => void send()} disabled={busy}>
            <MailIcon size={14} /> Send…
          </button>
          <button className="btn moss" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
