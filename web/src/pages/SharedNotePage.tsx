import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/http";
import {
  downloadSharedPdf,
  getSharedNote,
  reportShared,
  requestSharedVerification,
  sharedCtaUrl,
  sharedLogoUrl,
  verifyShared,
} from "../api/notes";
import { sharedStrings } from "../i18n/shared";
import type { SharedNoteView, SharedSection } from "../api/types";
import { AlertIcon, DownloadIcon } from "../components/icons";
import { RichText } from "../components/RichText";
import { FlagControl, SharedItems } from "../components/SharedItems";
import { safeFilename, saveBlob } from "../lib/exportNote";
import { formatDateTime } from "../lib/time";

/** Initials for the sender bar when there is no logo (or it fails to load). */
function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .join("") || "•"
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * The "Shared Outcome Page" (Sprint 19): what a client or partner sees
 * when a sender hands them a link. Read-only, no sign-in, no shell.
 *
 * The hierarchy is fixed on purpose — who sent it, what was agreed, who
 * does what, everything else folded away — because the recipient's job
 * is to check the outcome in a minute, not to read a transcript. The
 * product line under the sender bar is the loop: the CTA is a plain
 * link to a server redirect, so the click counts even without JS.
 */
export function SharedNotePage() {
  const { token = "" } = useParams<{ token: string }>();
  const [note, setNote] = useState<SharedNoteView | null>(null);
  const [error, setError] = useState<{ message: string; gone: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [logoFailed, setLogoFailed] = useState(false);
  // Sprint 23
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  const [changesDismissed, setChangesDismissed] = useState(false);
  const [tab, setTab] = useState<"notes" | "transcript" | null>(null);
  const [reporting, setReporting] = useState(false);
  const [reported, setReported] = useState(false);
  const t = sharedStrings(note?.lang);

  useEffect(() => {
    if (note?.lang) document.documentElement.lang = note.lang;
  }, [note?.lang]);

  const sendCode = async () => {
    setCodeError(null);
    try {
      await requestSharedVerification(token);
      setCodeSent(true);
    } catch (err) {
      setCodeError(errorMessage(err));
    }
  };

  const confirmCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setCodeError(null);
    try {
      setNote(await verifyShared(token, code.trim()));
      setCode("");
    } catch (err) {
      const c = err instanceof ApiError ? err.code : undefined;
      setCodeError(
        c === "code_invalid" ? t.codeWrong : c === "code_expired" || c === "too_many_attempts" ? t.codeExpired : errorMessage(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const report = async (reason: string) => {
    try {
      await reportShared(token, reason);
      setReported(true);
    } catch (err) {
      setError({ message: errorMessage(err), gone: false });
    } finally {
      setReporting(false);
    }
  };

  useEffect(() => {
    let live = true;
    setNote(null);
    setError(null);
    getSharedNote(token)
      .then((n) => live && setNote(n))
      .catch((err) => {
        if (!live) return;
        const gone = err instanceof ApiError && err.status === 404;
        setError({ message: gone ? "This link is no longer valid." : errorMessage(err), gone });
      });
    return () => {
      live = false;
    };
  }, [token]);

  useEffect(() => {
    document.title = note
      ? `${note.title || "Untitled note"} — ${note.sender.issuer_name}`
      : "Shared note";
  }, [note]);

  const onPdf = async () => {
    if (!note) return;
    setBusy(true);
    try {
      saveBlob(await downloadSharedPdf(token), `${safeFilename(note.title, note.code)}.pdf`);
    } catch (err) {
      setError({ message: errorMessage(err), gone: false });
    } finally {
      setBusy(false);
    }
  };

  const byRole = (role: SharedSection["role"]) => note?.sections.filter((s) => s.role === role) ?? [];
  const decisions = byRole("decisions");
  const actions = byRole("action_items");
  // "Anna, Tom" reads as a line under the title; anything longer (a
  // transcript that landed there, a roster with roles) is a section.
  const isRoster = (s: SharedSection) => !s.text.includes("\n") && s.text.length <= 160;
  const attendees = byRole("attendees").filter(isRoster);
  const prose = byRole("attendees").filter((s) => !isRoster(s));
  const other = byRole("other");
  const transcript = byRole("transcript");
  const hasNotes =
    decisions.length + actions.length + other.length + prose.length + (note?.items.length ?? 0) > 0;
  // The transcript sits behind its own tab. Notes first, unless there are none.
  const shownTab = tab ?? (hasNotes || transcript.length === 0 ? "notes" : "transcript");
  const brand = note?.product.brand_name ?? "Notes AI";
  const ctaHref = sharedCtaUrl(token);

  return (
    <div className="shared-shell">
      {/* ── sender bar ─────────────────────────────────────────── */}
      <header className="shared-bar">
        {note && (
          <span className="shared-sender">
            {note.sender.has_logo && !logoFailed ? (
              <img
                className="shared-logo"
                src={sharedLogoUrl(token)}
                alt=""
                onError={() => setLogoFailed(true)}
              />
            ) : (
              <span className="shared-logo shared-logo-initials" aria-hidden="true">
                {initials(note.sender.issuer_name)}
              </span>
            )}
            <span className="shared-brand">{note.sender.issuer_name}</span>
          </span>
        )}
        {!note && <span className="shared-brand">Shared note</span>}
        <span className="grow" />
        {note && (
          <span className="shared-status">
            <span className="help">{formatDate(note.updated_at)}</span>
          </span>
        )}
      </header>

      {/* ── product line: the loop (a paid workspace may switch it off) ── */}
      {(note?.product.cta_enabled ?? true) && (
        <div className="shared-product">
          <span>{note?.product.header_text ?? `Meeting summary generated by ${brand}.`}</span>{" "}
          <a className="shared-cta" href={ctaHref} rel="noreferrer">
            {t.createWorkspace}
          </a>
        </div>
      )}

      <main className="doc shared-doc">
        {error && (
          <div className={`banner ${error.gone ? "banner-warn" : "banner-danger"}`} role="alert">
            <AlertIcon size={15} />
            <span className="grow">{error.message}</span>
          </div>
        )}
        {!note && !error && (
          <p className="help" aria-busy="true">
            Loading…
          </p>
        )}
        {note && (
          <>
            <h1 className="shared-title">{note.title || "Untitled note"}</h1>
            {attendees.map((s) => (
              <p className="shared-attendees" key={s.section_key}>
                <span className="label">{s.name}:</span> {s.text}
              </p>
            ))}
            {note.changes && !changesDismissed && (
              <div className="banner banner-info shared-changes" role="status">
                <span className="grow">
                  <strong>{t.changesTitle}:</strong>{" "}
                  {note.changes.sections_changed.length > 0 && (
                    <>
                      {note.changes.sections_changed.length} {t.changesSections}
                    </>
                  )}
                  {note.changes.sections_changed.length > 0 && itemChangeCount(note.changes) > 0 && " · "}
                  {itemChangeCount(note.changes) > 0 && (
                    <>
                      {itemChangeCount(note.changes)} {t.changesItems}
                    </>
                  )}
                </span>
                <button className="btn ghost sm" onClick={() => setChangesDismissed(true)}>
                  {t.dismiss}
                </button>
              </div>
            )}
            {note.requires_verification && (
              <section className="doc-section shared-key shared-verify" aria-label={t.verifyTitle}>
                <h2 className="section-name">{t.verifyTitle}</h2>
                <p className="help">{t.verifyBody}</p>
                {!codeSent ? (
                  <button className="btn primary sm" onClick={() => void sendCode()}>
                    {t.sendCode}
                  </button>
                ) : (
                  <form className="shared-code" onSubmit={(e) => void confirmCode(e)}>
                    <p className="help">{t.codeSent}</p>
                    <label className="field">
                      <span className="label">{t.codeLabel}</span>
                      <input
                        className="input mono"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={7}
                        value={code}
                        disabled={busy}
                        onChange={(e) => setCode(e.target.value)}
                      />
                    </label>
                    <div className="row-actions">
                      <button className="btn primary sm" type="submit" disabled={busy || code.trim().length < 6}>
                        {t.confirm}
                      </button>
                      <button className="btn ghost sm" type="button" onClick={() => void sendCode()} disabled={busy}>
                        {t.sendCode}
                      </button>
                    </div>
                  </form>
                )}
                {codeError && (
                  <p className="help danger-text" role="alert">
                    {codeError}
                  </p>
                )}
              </section>
            )}

            {transcript.length > 0 && (
              <div className="tabs doc-tabs" role="tablist">
                <button className={`tab ${shownTab === "notes" ? "on" : ""}`} role="tab" aria-selected={shownTab === "notes"} onClick={() => setTab("notes")}>
                  {t.notesTab}
                </button>
                <button className={`tab ${shownTab === "transcript" ? "on" : ""}`} role="tab" aria-selected={shownTab === "transcript"} onClick={() => setTab("transcript")}>
                  {t.transcriptTab}
                </button>
              </div>
            )}

            {shownTab === "transcript" ? (
              <div className="doc-body shared-transcript">
                {transcript.map((s) => (
                  <section key={s.section_key} className="doc-section">
                    <RichText text={s.text} />
                    {note.can_respond && (
                      <FlagControl
                        token={token}
                        sectionKey={s.section_key}
                        flagged={note.my_flags.includes(s.section_key)}
                        onError={(message) => setError({ message, gone: false })}
                      />
                    )}
                  </section>
                ))}
              </div>
            ) : (
            <div className="doc-body">
              {prose.map((s) => (
                <section key={s.section_key} className="doc-section">
                  <h2 className="section-name">{s.name}</h2>
                  <RichText text={s.text} />
                  {note.can_respond && (
                    <FlagControl
                      token={token}
                      sectionKey={s.section_key}
                      flagged={note.my_flags.includes(s.section_key)}
                      onError={(message) => setError({ message, gone: false })}
                    />
                  )}
                </section>
              ))}
              {decisions.map((s) => (
                <section
                  key={s.section_key}
                  className={`doc-section shared-key ${note.changes?.sections_changed.includes(s.section_key) && !changesDismissed ? "changed" : ""}`}
                >
                  <h2 className="section-name">{t.agreed}</h2>
                  <RichText text={s.text} />
                  {note.can_respond && (
                    <FlagControl
                      token={token}
                      sectionKey={s.section_key}
                      flagged={note.my_flags.includes(s.section_key)}
                      onError={(message) => setError({ message, gone: false })}
                    />
                  )}
                </section>
              ))}
              {note.items.length > 0 ? (
                <SharedItems
                  token={token}
                  items={note.items}
                  canRespond={note.can_respond}
                  onError={(message) => setError({ message, gone: false })}
                  changedKeys={changesDismissed ? [] : [...(note.changes?.items_added ?? []), ...(note.changes?.items_changed ?? [])]}
                />
              ) : (
                actions.map((s) => (
                  <section key={s.section_key} className="doc-section shared-key">
                    <h2 className="section-name">{t.whoDoesWhat}</h2>
                    <RichText text={s.text} />
                  </section>
                ))
              )}
              {!hasNotes && <p className="help">{transcript.length > 0 ? t.noNotes : t.empty}</p>}
              {other.length > 0 && (
                <details className="shared-more" open={decisions.length === 0 && actions.length === 0}>
                  <summary>{t.more}</summary>
                  {other.map((s) => (
                    <section key={s.section_key} className="doc-section">
                      <h2 className="section-name">{s.name}</h2>
                      <RichText text={s.text} placeholder="Nothing entered." />
                      {note.can_respond && (
                        <FlagControl
                          token={token}
                          sectionKey={s.section_key}
                          flagged={note.my_flags.includes(s.section_key)}
                          onError={(message) => setError({ message, gone: false })}
                        />
                      )}
                    </section>
                  ))}
                </details>
              )}
            </div>
            )}

            <div className="shared-actions">
              <button className="btn sm" onClick={() => void onPdf()} disabled={busy}>
                <DownloadIcon size={14} /> {t.downloadPdf}
              </button>
            </div>
          </>
        )}
      </main>

      <footer className="shared-foot">
        {note ? (
          <>
            {t.sharedBy} {note.sender.shared_by_display} {t.via} {brand}
            {note.expires_at && (
              <>
                {" "}
                · {t.expires} {formatDate(note.expires_at)}
              </>
            )}
            {" · "}
          </>
        ) : (
          <>Shared with a link · </>
        )}
        <a href="/s/privacy" target="_blank" rel="noreferrer">
          {t.privacy}
        </a>
        {note && (
          <>
            {" · "}
            {reported ? (
              <span>{t.reportThanks}</span>
            ) : reporting ? (
              <span className="shared-report" role="group" aria-label={t.reportWhy}>
                {t.reportWhy}{" "}
                {Object.entries(t.reasons).map(([key, label]) => (
                  <button key={key} className="btn ghost sm" onClick={() => void report(key)}>
                    {label}
                  </button>
                ))}
              </span>
            ) : (
              <button className="link-btn" onClick={() => setReporting(true)}>
                {t.report}
              </button>
            )}
          </>
        )}
        {note && <span className="shared-updated"> · Updated {formatDateTime(note.updated_at)}</span>}
      </footer>
    </div>
  );
}

function itemChangeCount(c: NonNullable<SharedNoteView["changes"]>): number {
  return c.items_added.length + c.items_removed.length + c.items_changed.length;
}
